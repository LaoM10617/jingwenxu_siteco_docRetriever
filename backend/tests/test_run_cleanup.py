import sqlite3
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from app.run_cleanup import delete_session, retry_purges
from app.documents import DocumentError
from test_conversation_runs import setup, direct


def test_session_delete_retries_checkpoint_cleanup_without_reexecution(tmp_path, monkeypatch):
    runs, sid, model, _ = setup(tmp_path, [direct()])
    run = runs.submit(sid, 'q', 'Hello', expected_data_version=0, expected_rule_version=0)
    assert runs.execute(run['run_id'])['status'] == 'completed'
    retry_purges(runs)
    original = SqliteSaver.delete_thread
    def fail(*args):
        raise sqlite3.OperationalError('simulated checkpoint disk unavailable')
    monkeypatch.setattr(SqliteSaver, 'delete_thread', fail)
    with pytest.raises(sqlite3.OperationalError):
        delete_session(runs, sid)
    with pytest.raises(DocumentError):
        runs.sessions.get(sid)
    with runs._db() as db:
        assert db.execute('SELECT count(*) FROM conversation_purges').fetchone()[0] == 1
    monkeypatch.setattr(SqliteSaver, 'delete_thread', original)
    retry_purges(runs)
    with sqlite3.connect(runs.checkpoints) as db:
        assert db.execute('SELECT count(*) FROM checkpoints WHERE thread_id=?', (run['run_id'],)).fetchone()[0] == 0
    assert len(model.calls) == 1


def test_permanent_source_deletion_cleans_graph_derived_data_and_keeps_history(tmp_path):
    from fastapi.testclient import TestClient
    from test_run_api import Model, prepared, upload, submission, poll
    model = Model()
    with TestClient(prepared(tmp_path, model)) as client:
        sid, did = upload(client, tmp_path)
        base = f'/api/sessions/{sid}/runs'
        run = client.post(base, json=submission(client, sid)).json()
        assert poll(client, sid, run['run_id'], {'completed', 'failed'})['status'] == 'completed'
        assert client.post(f'/api/documents/{did}/trash').status_code == 200
        assert client.delete(f'/api/documents/{did}').status_code == 200
        saved = client.get(base+'/'+run['run_id']).json()
        assert saved['status'] == 'completed' and saved['answer']
        assert saved['source_available'] is False
        runs = client.app.state.runs
        with runs._db() as db:
            assert db.execute('SELECT count(*) FROM conversation_tasks').fetchone()[0] == 0
            assert db.execute('SELECT count(*) FROM conversation_evidence').fetchone()[0] == 0
        with sqlite3.connect(runs.checkpoints) as db:
            assert db.execute('SELECT count(*) FROM checkpoints').fetchone()[0] == 0
