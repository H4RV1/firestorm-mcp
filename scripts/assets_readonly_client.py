"""Attach through persistent MCP stdio, read status and one fresh inventory folder.

No login, launch, credentials, asset submission, chat or world mutation. Use the
same --data-dir as the viewer's LEAP launcher. This example requires MCP SDK v2.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

from mcp import Client, StdioServerParameters
from firestorm_mcp.probe import unpack


async def inspect(args):
    command = ['-m', 'firestorm_mcp.server', '--tool-profile', 'compact', '--data-dir', str(args.data_dir.resolve())]
    if args.viewer_dir:
        command += ['--viewer-dir', str(args.viewer_dir.resolve())]
    async with Client(StdioServerParameters(command=sys.executable, args=command)) as session:
        async def call(name, **values):
            result = unpack(await session.call_tool(name, values))
            if result.get('ok') is False:
                raise RuntimeError(json.dumps(result['failure']))
            return result
        status = await call('assets_status')
        if status.get('contractVersion') != 1 or status.get('bridgeContractVersion') != 1:
            raise RuntimeError('Incompatible viewer/helper; this example requires contract v1')
        print(json.dumps({'status': status}, indent=2))
        if not status['connected']:
            return
        await call('control_acquire', label='Read-only inventory consumer example', seconds=60)
        try:
            expectation = {key: status[key] for key in ('avatarId', 'grid', 'generation')}
            result = await call('assets_list_inventory', request_id=str(uuid4()), expected=expectation,
                                folder_id=args.folder_id or status['rootFolderId'])
            deadline = time.monotonic()+40
            while result['state'] in ('queued', 'running'):
                if time.monotonic() > deadline:
                    raise TimeoutError('Stopped waiting; a read job may still finish')
                await asyncio.sleep(.25)
                result = await call('assets_job', job_id=result['jobId'])
            print(json.dumps({'inventoryJob': result}, indent=2))
        finally:
            await call('control_release')
    # Closing stdio detaches this consumer; it never logs out Firestorm.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--viewer-dir', type=Path)
    parser.add_argument('--folder-id')
    asyncio.run(inspect(parser.parse_args()))
