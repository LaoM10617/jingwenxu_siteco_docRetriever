from threading import Event
from fastapi.testclient import TestClient
from test_run_api import Model, prepared, upload, submission, poll


def test_resume_in_worker_exit_window_is_not_left_queued(tmp_path):
    model = Model()
    with TestClient(prepared(tmp_path, model)) as client:
        sid, _ = upload(client, tmp_path)
        reached, release = Event(), Event()
        runs = client.app.state.runs
        original = runs.execute
        def delayed_exit(run_id):
            result = original(run_id)
            if result['status'] == 'waiting':
                reached.set()
                assert release.wait(5)
            return result
        runs.execute = delayed_exit
        base = f'/api/sessions/{sid}/runs'
        run = client.post(base, json=submission(client, sid, question='Clarify first')).json()
        try:
            assert reached.wait(5)
            response = client.post(base+'/'+run['run_id']+'/resume', json={'reply':'A power'})
            assert response.status_code == 202, response.text
        finally:
            release.set()
        assert poll(client, sid, run['run_id'], {'completed', 'failed'})['status'] == 'completed'
