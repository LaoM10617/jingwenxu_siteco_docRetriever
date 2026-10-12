from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.execution_api import router
from app.python_executor import PYTHON_IMAGE


def test_worker_api_is_closed_without_or_with_wrong_token():
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(execution_worker_token=SecretStr(''))
    with TestClient(app) as client:
        assert client.post('/api/execution-worker/claim', json={'worker_id': 'w'}).status_code == 401
        app.state.settings.execution_worker_token = SecretStr('test-only')
        assert client.post('/api/execution-worker/claim', json={'worker_id': 'w'},
                           headers={'Authorization': 'Bearer wrong'}).status_code == 401
        app.state.execution_jobs = SimpleNamespace(claim=lambda worker, image: None)
        assert client.post('/api/execution-worker/claim', json={'worker_id': 'w', 'image': PYTHON_IMAGE},
                           headers={'Authorization': 'Bearer test-only'}).json() == {'job': None}


def test_worker_cannot_choose_execution_options():
    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(execution_worker_token=SecretStr('test-only'))
    app.state.execution_jobs = SimpleNamespace()
    with TestClient(app) as client:
        response = client.post('/api/execution-worker/claim', json={'worker_id': 'w', 'image': 'evil'},
                               headers={'Authorization': 'Bearer test-only'})
        assert response.status_code == 422
