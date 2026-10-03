import asyncio
import json
from types import SimpleNamespace

import pytest

from firestorm_mcp.executor import execute, validate_plan
from firestorm_mcp.server import Tools


class Session:
    def __init__(self, tmp_path, failure=None, changed=False, queued=False):
        self.tools = Tools(tmp_path)
        self.calls, self.leased = [], False
        self.failure, self.changed, self.queued = failure, changed, queued

    async def list_tools(self):
        return SimpleNamespace(tools=self.tools.definitions_list(False))

    async def call_tool(self, name, args):
        self.calls.append(name)
        if name == self.failure: raise ConnectionError('Synthetic transport loss')
        if name == 'connection_status':
            result = {'connected': True, 'bridge_generation': 'changed' if self.changed and self.leased else 'initial'}
        elif name == 'control_acquire':
            result = {'acquired': True, 'acquired_new': not self.leased}; self.leased = True
        elif name == 'object_selection' and self.queued:
            result = {'state': 'running', 'jobId': 'synthetic'}
        else: result = {}
        return SimpleNamespace(is_error=False, content=[SimpleNamespace(type='text', text=json.dumps(result))])


def plan(*tools):
    return {'version': 1, 'calls': [{'tool': tool, 'arguments': {}} for tool in tools]}


def test_executor_uses_one_session_and_releases(tmp_path):
    session = Session(tmp_path)
    result = asyncio.run(execute(session, plan('object_selection', 'script_sessions')))
    assert result['complete']
    assert session.calls.count('capabilities_refresh') == 1
    assert session.calls[-1] == 'control_release'


@pytest.mark.parametrize('failure,changed,queued,reason', [
    ('object_selection', False, False, 'step_error'), (None, True, False, 'connection_changed'),
    (None, False, True, 'job_pending')])
def test_executor_stops_and_releases_without_retry(tmp_path, failure, changed, queued, reason):
    session = Session(tmp_path, failure, changed, queued)
    result = asyncio.run(execute(session, plan('object_selection', 'script_sessions')))
    assert result['stopped'] == reason and not result['complete']
    assert 'script_sessions' not in session.calls
    assert session.calls.count('object_selection') <= 1
    assert session.calls[-1] == 'control_release'


def test_executor_validates_entire_plan_before_contact(tmp_path):
    session = Session(tmp_path)
    p = plan('object_selection', 'ui_click')
    with pytest.raises(ValueError, match='allow-writes'):
        asyncio.run(execute(session, p))
    assert not session.calls
    with pytest.raises(Exception, match='path'):
        asyncio.run(execute(session, p, allow_writes=True))
    assert not session.calls
