from fastapi.testclient import TestClient

from app.main import create_app
from test_app import settings_for
from test_csv_lifecycle import contents, terminal
from test_csv_parsing import row


def test_session_http_scope_versions_history_and_restart(tmp_path):
    configuration = settings_for(tmp_path)
    with TestClient(create_app(configuration)) as client:
        sid = client.post('/api/sessions').json()['session_id']
        base = f'/api/sessions/{sid}'
        sources = []
        for label in ('A', 'B', 'C'):
            doc = client.post('/api/documents', params={'session_id': sid}, files={
                'file': (label + '.csv', contents([row(label, '1,00')]).getvalue())}).json()
            assert terminal(client.app.state.documents, doc['document_id'])['status'] == 'ready'
            sources.append({'document_id': doc['logical_document_id'], 'version_id': doc['version_id']})
        a, b, c = sources
        rules = client.put(base + '/rules', json={
            'expected_rule_version': 0, 'default_sources': [b], 'purpose_sources': {'price': [c]}})
        assert rules.status_code == 200, rules.text
        state = rules.json()
        common = {'expected_rule_version': state['rule_version'], 'expected_data_version': state['data_version']}
        explicit = client.post(base + '/snapshots', json={**common, 'request_id': 'one',
            'purpose': 'price', 'explicit_sources': [a]})
        assert explicit.status_code == 201, explicit.text
        assert explicit.json()['scope']['documents'] == [a]
        priced = client.post(base + '/snapshots', json={**common, 'request_id': 'two', 'purpose': 'price'})
        assert priced.json()['scope']['documents'] == [c]
        default = client.post(base + '/snapshots', json={**common, 'request_id': 'three'})
        assert default.json()['scope']['documents'] == [b]
        stale = client.put(base + '/rules', json={'expected_rule_version': 0, 'default_sources': [a]})
        assert stale.status_code == 409
        assert client.post(base + '/messages', json={'message_id': 'm1', 'content': 'Keep this conversation'}).status_code == 201
        assert client.post(base + '/messages', json={'message_id': 'm1', 'content': 'Different'}).status_code == 409
    with TestClient(create_app(configuration)) as client:
        assert client.get(base).json()['default_sources'] == [b]
        assert client.get(base + '/messages').json()[0]['content'] == 'Keep this conversation'
        assert client.get(base + '/snapshots/' + explicit.json()['snapshot_id']).json() == explicit.json()
        foreign = client.post('/api/sessions').json()['session_id']
        assert client.get(f'/api/sessions/{foreign}/snapshots/' + explicit.json()['snapshot_id']).status_code == 404
        assert client.delete(base).status_code == 200
        assert client.get(base).status_code == 404
        assert len(client.get('/api/documents').json()) == 3


def test_session_api_rejects_technical_fields_and_invalid_versions(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        sid = client.post('/api/sessions').json()['session_id']
        base = f'/api/sessions/{sid}'
        assert client.post(base + '/snapshots', json={'request_id': 'x', 'expected_data_version': True,
            'expected_rule_version': 0}).status_code == 422
        assert client.post(base + '/messages', json={'message_id': 'x', 'content': 'Hi', 'role': 'assistant'}).status_code == 422
        assert client.post(base + '/sources', json={'source': {'document_id': 'x', 'version_id': 'x'},
            'expected_data_version': 0}).status_code == 409
