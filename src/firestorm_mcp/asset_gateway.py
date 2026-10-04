"""Authoritative asset gateway in the viewer-owned helper, shared by MCP clients.

All paths, credentials and remote URLs remain in the viewer/helper. The durable
intent is committed BEFORE submit. Lost acknowledgements never cause replay.
"""
import base64
import hashlib
import sqlite3
import time
import uuid

from .asset_contract import AssetError, CHUNK_BYTES, MAX_AUDIO, WRITES, fingerprint, identifier, validate


class AssetGateway:
    def __init__(self, bridge, journal):
        self.bridge, self.journal = bridge, journal
        self.stages = {}
        self.jobs = {}
        self.synced_lease = None
        self.synced_until = 0

    def native(self, op, args):
        value = self.bridge.call('FSMCPAssets', op, args, expect_reply=True, timeout=5)
        if not isinstance(value, dict) or value.get('schema_version') != 1:
            raise AssetError('schema_mismatch', 'Unsupported native asset contract.')
        return value

    def sync_lease(self):
        b = self.bridge
        seconds = max(0, b.lease_until - time.monotonic())
        lease = str(uuid.uuid5(uuid.NAMESPACE_URL, b.generation + str(b.owner))) if b.owner and seconds else ''
        # The native lease remains authoritative on every execution. Avoid an
        # extra viewer round trip for every staging chunk and job poll.
        now = time.monotonic()
        if lease != self.synced_lease or self.synced_until - now < 30 or b.lease_until > self.synced_until + 1:
            # An unknown sync outcome cannot justify skipping rollback.
            self.synced_lease, self.synced_until = None, 0
            result = self.native('lease', {'leaseId': lease, 'seconds': seconds})
            if not result.get('ok'):
                raise AssetError('lease_sync_failed', 'Native asset lease synchronization was refused; control was not established.')
            self.synced_lease, self.synced_until = lease, now + seconds

        return lease

    def revoked(self):
        if 'FSMCPAssets' in self.bridge.apis:
            self.sync_lease()

    def handle(self, op, args):
        try:
            return self._handle(op, dict(args or {}))
        except AssetError as exc:
            return {'schema_version': 1, 'ok': False, 'failure': exc.details}
        except (sqlite3.Error, OSError):
            # A persistence error may follow an acknowledged native submission.
            # Never expose local paths or turn a lost durable update into failure.
            failure = dict(code='journal_unavailable',
                message='Durable request storage is unavailable. Restore it and inspect the original request before retrying.',
                unknownOutcome=op in ('submit', 'job', 'request', 'cancel'))
            for key in ('requestId', 'jobId'):
                if isinstance(args, dict) and key in args:
                    failure[key] = args[key]
            return {'schema_version': 1, 'ok': False, 'failure': failure}

    def _handle(self, op, args):
        if op == 'lease' or 'leaseId' in args:
            raise AssetError('reserved_operation', 'Lease synchronization is internal to the authenticated bridge.')
        if op == 'status':
            result = self.native(op, {})
            result['bridgeGeneration'] = self.bridge.generation
            result['bridgeContractVersion'] = 1
            result.setdefault('limits', {}).update(journalRequests=self.journal.LIMIT if self.journal else 0,
                                                   bridgeHttpBytes=16*1024*1024)
            return result
        if not self.bridge.owner or self.bridge.lease_until <= time.monotonic():
            raise AssetError('lease_required', 'Acquire an active bounded lease for asset operations.')
        lease = self.sync_lease()
        args['leaseId'] = lease
        if op == 'stage':
            stage_id = identifier(args.get('stageId'))
            value = args.get('data')
            if not isinstance(value, dict) or set(value) != {'$binary_base64'} or not isinstance(value['$binary_base64'], str) or len(value['$binary_base64']) > 4*((CHUNK_BYTES+2)//3):
                raise AssetError('payload_too_large', 'Use binary staging chunks of at most 49152 bytes.')
            try:
                data = base64.b64decode(value['$binary_base64'], validate=True)
            except ValueError:
                raise AssetError('invalid_request', 'Invalid staging base64.') from None
            self.stages = {key: entry for key, entry in self.stages.items() if entry['expires'] > time.monotonic()}
            entry = self.stages.get(stage_id)
            if entry is None:
                if len(self.stages) >= 4:
                    raise AssetError('stage_limit', 'Four audio stages are already retained.')
                entry = dict(owner=lease, size=0, digest=hashlib.sha256(), expires=time.monotonic()+120)
                self.stages[stage_id] = entry
            if entry['owner'] != lease or type(args.get('offset')) is not int or args['offset'] != entry['size']:
                raise AssetError('stage_offset', 'Stage owner or offset mismatch; discard and restage.')
            if len(data) > CHUNK_BYTES or entry['size'] + len(data) > MAX_AUDIO:
                raise AssetError('payload_too_large', 'Decoded sound limit is 8 MiB.')
            result = self.native(op, args)
            if result.get('ok'):
                entry['digest'].update(data); entry['size'] += len(data); entry['expires'] = time.monotonic()+120
            return result
        if op == 'discard':
            entry = self.stages.get(args.get('stageId'))
            if entry and entry['owner'] != lease:
                raise AssetError('lease_required', 'Stage belongs to another lease.')
            result = self.native(op, args)
            if result.get('ok'): self.stages.pop(args.get('stageId'), None)
            return result
        if op == 'submit':
            request = identifier(args.get('requestId'))
            kind, arguments, expected = args.get('kind'), dict(args.get('arguments') or {}), args.get('expected') or {}
            if {'creationReceipt', 'intent', 'uploadId'} & arguments.keys():
                raise AssetError('reserved_field', 'Receipts and reconciliation intents are supplied by the journal.')
            # The transport stage UUID is not part of logical identity. SHA256 is verified below.
            logical = {k: v for k, v in arguments.items() if k != 'stageId'}
            validate(kind, logical, expected)
            digest = fingerprint(kind, logical, expected)
            existing = self.journal.get(request) if self.journal else None
            if existing:
                if existing['fingerprint'] != digest:
                    raise AssetError('request_conflict', 'Request ID was already bound to different arguments or session expectations.')
                return self.saved(existing)
            if kind == 'reconcile':
                old = self.journal.get(identifier(arguments.get('originalRequestId')))
                if not old:
                    raise AssetError('request_missing', 'Original intent is not in this bridge journal.')
                if old['expected']['avatarId'] != expected['avatarId'] or old['expected']['grid'] != expected['grid']:
                    raise AssetError('session_changed', 'Original intent belongs to another account or grid.')
                if old.get('state') == 'succeeded':
                    return self.saved(old)
                arguments['intent'] = {key: old.get(key, {}) for key in ('kind', 'arguments', 'expected', 'acknowledged')}
                if old['kind'] == 'commitUpload':
                    preparation = self.journal.get(old['arguments']['preparationRequestId'])
                    if not preparation or preparation['kind'] != 'prepareUpload':
                        raise AssetError('preparation_missing', 'Saved preparation is required for reconciliation.')
                    arguments['intent']['arguments'] = preparation['arguments']
            if kind == 'commitUpload':
                preparation = self.journal.get(arguments['preparationRequestId'])
                if not preparation or preparation['kind'] != 'prepareUpload' or preparation.get('state') != 'succeeded':
                    raise AssetError('preparation_missing', 'Poll a successful preparation before committing.')
                if preparation['expected'] != expected:
                    raise AssetError('session_changed', 'Preparation belongs to another viewer session.')
                quote = preparation.get('result', {})
                if type(quote.get('cost')) is not int or quote['cost'] != arguments['approvedCost']:
                    raise AssetError('cost_mismatch', 'approvedCost must exactly match the prepared cost.')
                arguments['uploadId'] = identifier(quote.get('uploadId'))
            if kind == 'trashEmptyFolder':
                receipt = self.journal.get(identifier(arguments.get('creationRequestId')))
                if not receipt or receipt.get('state') != 'succeeded' or receipt['kind'] != 'createFolder':
                    raise AssetError('creation_unverified', 'Cleanup requires a journaled confirmed folder creation.')
                arguments['creationReceipt'] = {key: receipt.get(key, {}) for key in ('kind', 'arguments', 'expected', 'result')}
            if kind in ('uploadSound', 'prepareUpload'):
                entry = self.stages.get(arguments.get('stageId'))
                digest_key = 'audioSha256' if kind == 'uploadSound' else 'payloadSha256'
                if not entry or entry['owner'] != lease or entry['expires'] <= time.monotonic() or not entry['size'] or entry['digest'].hexdigest() != arguments.get(digest_key):
                    raise AssetError('stage_mismatch', 'Complete staged bytes do not match the declared SHA256.')
            if kind in WRITES or kind == 'reconcile':

                if not self.journal:
                    raise AssetError('journal_unavailable', 'A durable bridge journal is required for mutations.')
                record, fresh = self.journal.reserve(request, digest, kind, logical, expected)
                if not fresh:
                    return self.saved(record)
            native_args = dict(args, requestId=request, fingerprint=digest, arguments=arguments)
            try:
                result = self.native('submit', native_args)
            except Exception:
                if kind in WRITES or kind == 'reconcile':
                    raise AssetError('outcome_unknown', 'Submission acknowledgement was lost. Do not replay; poll or reconcile the saved request.', True, requestId=request) from None
                raise
            if result.get('ok') and (result.get('requestId') != request or result.get('fingerprint') != digest):
                raise AssetError('request_conflict', 'Submission acknowledgement differs from its durable intent; inspect the original request.', True, requestId=request)
            if result.get('jobId'):
                self.jobs[result['jobId']] = (request, kind, logical.get('originalRequestId'))
                # Bound local bookkeeping independently from the persistent write journal.
                if len(self.jobs) > 256:
                    self.jobs.pop(next(iter(self.jobs)))
            if kind in WRITES or kind == 'reconcile':
                self.record(request, result, submission=True)
            return result
        if op in ('job', 'cancel'):
            if op == 'cancel' and self.journal:
                bound = self.journal.by_job(args.get('jobId'))
                if bound:
                    observed = self.native('job', args)
                    if not observed.get('ok'):
                        return self.saved(bound)
                    if observed.get('fingerprint') != bound['fingerprint'] or observed.get('requestId') != bound['requestId']:
                        raise AssetError('request_conflict', 'Native job identity differs from its durable intent; cancellation was not dispatched.', True)
            result = self.native(op, args)
            job_id = args.get('jobId')
            entry = self.jobs.get(job_id)
            durable = self.journal.by_job(job_id) if self.journal else None
            if durable:
                entry = (durable['requestId'], durable['kind'], durable['arguments'].get('originalRequestId'))
            if entry:
                request, kind, original = entry
                saved = self.journal.get(request) if self.journal else None
                if result.get('ok') and saved and (result.get('fingerprint') != saved['fingerprint'] or result.get('requestId') != request):
                    raise AssetError('request_conflict', 'Native job identity differs from its durable intent.', True)
                if kind in WRITES or kind == 'reconcile':
                    self.record(request, result)
                    if not result.get('ok'):
                        return self.saved(self.journal.get(request))
                if kind == 'reconcile' and original and result.get('state') == 'succeeded':
                    self.journal.update(original, state='succeeded', result=result['result'], unknownOutcome=False, reconciled=True)
            return result
        if op == 'request':
            record = self.journal.get(identifier(args.get('requestId')))
            if not record:
                raise AssetError('request_missing', 'Request is not in the durable journal.')
            if record.get('state') not in ('succeeded', 'failed', 'cancelled'):
                lookup = {'jobId': record['jobId']} if record.get('jobId') else {'requestId': record['requestId']}
                result = self.native('job', dict(lookup, leaseId=lease))
                if result.get('ok'):
                    if result.get('fingerprint') != record['fingerprint'] or result.get('requestId') != record['requestId']:
                        raise AssetError('request_conflict', 'Retained native job has a different operation fingerprint.', True)
                    self.record(record['requestId'], result)
                    if record['kind'] == 'reconcile' and result.get('state') == 'succeeded':
                        self.journal.update(record['arguments']['originalRequestId'], state='succeeded', result=result['result'], unknownOutcome=False, reconciled=True)
                    return result
            return self.saved(record)
        if op not in ('watch', 'events', 'unwatch'):
            raise AssetError('unsupported_operation', 'Unsupported asset transport operation.')
        return self.native(op, args)

    def record(self, request, result, submission=False):
        if not result.get('ok') and not submission:
            # Missing/evicted native observation is not proof that the write failed.
            return
        fields = {key: result[key] for key in ('jobId', 'state', 'phase', 'submitted', 'result', 'failure', 'acknowledged') if key in result}
        if not result.get('ok'):
            fields['state'] = 'failed'; fields['unknownOutcome'] = False
        else:
            fields['unknownOutcome'] = result.get('state') not in ('succeeded', 'failed', 'cancelled')
        self.journal.update(request, **fields)

    @staticmethod
    def saved(record):
        state = record.get('state')
        if state not in ('succeeded', 'failed', 'cancelled'):
            state = 'unknown'
        out = {key: record[key] for key in ('requestId', 'jobId', 'result', 'failure', 'acknowledged') if key in record}
        out.update(schema_version=1, ok=True, state=state, unknownOutcome=state == 'unknown', journaled=True)
        if state == 'unknown':
            out['failure'] = dict(code='outcome_unknown', message='A prior intent exists. Poll the saved job or reconcile; this call did not replay it.', unknownOutcome=True)
        return out
