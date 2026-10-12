"""The persistent session graph is the only public question orchestrator."""
from fastapi.testclient import TestClient
from app.main import create_app
from app.processing import DocumentProcessor
from test_app import settings_for


def test_legacy_question_routes_and_worker_are_retired(tmp_path):
    app = create_app(settings_for(tmp_path), processor=DocumentProcessor())
    with TestClient(app) as client:
        assert client.post('/api/questions', json={}).status_code == 404
        assert client.get('/api/questions/old').status_code == 404
        assert client.get('/api/questions/old/csv/0').status_code == 404
        assert not hasattr(app.state, 'questions')
        assert client.post('/api/sessions').status_code == 201
