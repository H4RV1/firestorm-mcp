"""Bridge-owned durable intent log. No asset bytes, credentials or capability URLs."""
import json
import os
import sqlite3
import time

from .asset_contract import AssetError


class AssetJournal:
    LIMIT = 10000

    def __init__(self, path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (request TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, record TEXT NOT NULL)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def get(self, request):
        with self.connect() as db:
            row = db.execute('SELECT record FROM jobs WHERE request=?', (request,)).fetchone()
            return json.loads(row[0]) if row else None

    def reserve(self, request, fingerprint, kind, arguments, expected):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fingerprint,record FROM jobs WHERE request=?', (request,)).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise AssetError('request_conflict', 'Request ID was already bound to different arguments.')
                return json.loads(row[1]), False
            if db.execute('SELECT count(*) FROM jobs').fetchone()[0] >= self.LIMIT:
                raise AssetError('journal_full', 'Durable journal capacity reached; archive only after reconciling outstanding work.')
            record = dict(requestId=request, fingerprint=fingerprint, kind=kind,
                          arguments=arguments, expected=expected, created=time.time(),
                          state='unknown', unknownOutcome=True)
            db.execute('INSERT INTO jobs VALUES (?,?,?)', (request, fingerprint, json.dumps(record)))
            return record, True

    def update(self, request, **fields):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT record FROM jobs WHERE request=?', (request,)).fetchone()
            if not row:
                raise AssetError('request_missing', 'Request is not in this bridge journal.')
            record = json.loads(row[0]); record.update(fields)
            db.execute('UPDATE jobs SET record=? WHERE request=?', (json.dumps(record, default=str), request))
            return record
