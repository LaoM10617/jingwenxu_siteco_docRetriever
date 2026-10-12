"""M3.4 failures remain execution failures across task publication and recovery."""
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings
from app.generation import StructuredModel
from app.processing import DocumentProcessor
from test_app import settings_for
from document_test_helpers import ready


def terminal(client, sid, identity):
    for _ in range(250):
        result = client.get(f'/api/sessions/{sid}/runs/{identity}')
        assert result.status_code == 200
        task = result.json()
        if task['status'] in ('completed','failed'):
            return task
        time.sleep(.02)
    pytest.fail('Task did not reach a terminal state')


@pytest.mark.parametrize('provider', ['gemini','groq'])
@pytest.mark.parametrize('failure,code', [
    (401,'generation_authentication_failed'), (429,'generation_rate_limited'),
    (503,'generation_provider_unavailable'), ('bad-json','generation_invalid_output'),
    ('timeout','generation_timeout')])
def test_sdk_failure_is_published_once_without_an_absence_of_evidence_answer(tmp_path, provider, failure, code):
    calls=[]
    def respond(request):
        calls.append(True)
        if failure == 'timeout':
            raise httpx.ReadTimeout('private-provider-detail',request=request)
        if isinstance(failure,int):
            return httpx.Response(failure,json={'error':{'code':failure,'message':'private-provider-detail'}})
        if provider == 'gemini':
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP',
                'content':{'parts':[{'text':'not JSON'}],'role':'model'}}]})
        return httpx.Response(200,json={'id':'t','object':'chat.completion','created':1,'model':'test',
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'not JSON'}}]})
    model = StructuredModel(Settings(_env_file=None,data_dir=tmp_path,generation_provider=provider,
        gemini_api_key='fake',groq_api_key='fake'),transport=httpx.MockTransport(respond))
    with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=model)) as client:
        doc=ready(client)
        sid = client.post('/api/sessions').json()['session_id']
        body={'request_id':'r','question':'Hello','expected_data_version':0,'expected_rule_version':0}
        path=f'/api/sessions/{sid}/runs'
        submitted=client.post(path,json=body)
        assert submitted.status_code == 202
        qid=submitted.json()['run_id']
        task=terminal(client,sid,qid)
        assert task['status'] == 'failed'
        assert task['error']['code'] == code and task['answer'] is None
        assert 'private-provider-detail' not in str(task)
        assert client.post(path,json=body).json()['run_id'] == qid
        assert terminal(client,sid,qid) == task
        assert len(calls) == 1
        assert client.get('/api/documents/'+doc).json()['status'] == 'ready'
