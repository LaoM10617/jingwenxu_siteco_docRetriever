"""Real worker processes and Docker; controlled HTTP fault injection, no models."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
from threading import Thread
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.agent_protocol import TaskPackage, ScopeSnapshot
from app.execution_jobs import ExecutionJobs
from app.host_worker import HostWorker
from app.questions import QuestionBudget


def eventually(check, timeout=25):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = check()
        if value:
            return value
        time.sleep(.1)
    raise RuntimeError('Probe condition timed out')


def containers(owner):
    result = subprocess.run(['docker', 'container', 'ls', '-aq', '--filter',
        'label=siteco.execution.owner=' + owner], capture_output=True, check=True, timeout=15)
    return result.stdout.decode().split()


def running_container(owner):
    for identity in containers(owner):
        result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', identity],
                                capture_output=True, check=True, timeout=15)
        if result.stdout.decode().strip() == 'true':
            return identity
    return None


def run_case(target, image, mode):
    target.mkdir(parents=True)
    database = target / 'app.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE conversation_runs(run_id TEXT PRIMARY KEY,stop_requested INTEGER)')
        db.execute("INSERT INTO conversation_runs VALUES ('r',0)")
    jobs = ExecutionJobs(database, expected_image=image)
    task = TaskPackage(session_id='s', turn_id='t', run_id='r', task_id='task',
                       specialist='csv', objective='Lifecycle probe', scope=ScopeSnapshot(documents=()))
    token = secrets.token_urlsafe(32)
    observed = {'claims': 0, 'completions': [], 'lost_responses': 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.headers.get('Authorization') != 'Bearer ' + token:
                self.send_error(401)
                return
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path.endswith('/claim'):
                job = jobs.claim(body['worker_id'], body['image'])
                observed['claims'] += int(job is not None)
                response = {'job': job}
            else:
                identity = self.path.split('/')[-2]
                if self.path.endswith('/heartbeat'):
                    response = {'continue': jobs.heartbeat(identity, body['lease_token'])}
                else:
                    accepted = jobs.complete(identity, body['lease_token'], body['result'])
                    observed['completions'].append({'accepted': accepted, 'status': body['result']['status']})
                    response = {'accepted': accepted}
                    if mode == 'lost_ack' and not observed['lost_responses']:
                        observed['lost_responses'] += 1
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    work_dir = target / 'worker'
    owner = HostWorker(work_dir, None, image).owner
    env = os.environ.copy()
    env['EXECUTION_WORKER_TOKEN'] = token
    processes, logs = [], []

    def start_worker():
        log = (target / f'worker-{len(processes)}.log').open('w', encoding='utf-8')
        logs.append(log)
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/run_python_worker.py'),
            '--backend', f'http://127.0.0.1:{server.server_port}', '--work-dir', str(work_dir), '--image', image],
            cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        processes.append(process)
        return process

    def acknowledged():
        with sqlite3.connect(work_dir / 'worker.sqlite3') as db:
            return db.execute("SELECT count(*) FROM jobs WHERE status='acknowledged' AND result IS NULL").fetchone()[0] == 1

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        script = "import json; print(json.dumps({'sum':5}))" if mode == 'lost_ack' else 'import time; time.sleep(60)'
        future = pool.submit(jobs.execute, task, script, {}, QuestionBudget())
        worker = start_worker()
        if mode in ('kill_recover', 'stop'):
            observed['running_container_verified'] = eventually(lambda: running_container(owner))
            if mode == 'kill_recover':
                worker.kill()
                worker.wait(10)
                assert running_container(owner), 'The forced kill did not leave a running orphan to test'
                start_worker()
                result = future.result(timeout=30)
                assert result.status == 'interrupted'
                eventually(acknowledged)
                assert observed['claims'] == 1, 'Recovery must not re-execute work'
            else:
                with sqlite3.connect(database) as db:
                    db.execute('UPDATE conversation_runs SET stop_requested=1')
                try:
                    future.result(timeout=20)
                    raise AssertionError('Stopped job unexpectedly produced a result')
                except Exception as error:
                    assert getattr(error, 'code', None) == 'source_unavailable'
                eventually(acknowledged)
                assert observed['completions'][-1] == {'accepted': False, 'status': 'cancelled'}
        else:
            result = future.result(timeout=30)
            assert result.status == 'completed' and result.value == {'sum': 5}
            eventually(acknowledged)
            assert observed['claims'] == 1
            assert observed['lost_responses'] == 1
            assert observed['completions'] == [{'accepted': True, 'status': 'completed'}] * 2
        eventually(lambda: not containers(owner))
        assert not list((work_dir / 'staging').iterdir())
        assert not list((work_dir / 'inputs').iterdir())
        return {'mode': mode, 'status': 'passed', **observed, 'containers_remaining': 0}
    finally:
        with sqlite3.connect(database) as db:
            db.execute('UPDATE conversation_runs SET stop_requested=1')
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(10)
        for container in containers(owner):
            subprocess.run(['docker', 'rm', '--force', container], capture_output=True, check=True, timeout=15)
        server.shutdown()
        server.server_close()
        thread.join(5)
        pool.shutdown(wait=True)
        for log in logs:
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    target = ROOT / 'data/stage-d' / ('worker-recovery-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    target.mkdir(parents=True)
    receipt = {'image': args.image, 'checks': [], 'status': 'running',
               'boundary': 'real ExecutionJobs, worker process, HTTP and Docker; controlled HTTP fault injection; no model'}
    try:
        for mode in ('kill_recover', 'stop', 'lost_ack'):
            receipt['checks'].append(run_case(target / mode, args.image, mode))
        receipt['status'] = 'passed'
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['error_type'] = type(error).__name__
        raise
    finally:
        (target / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps({'receipt': str(target / 'receipt.json'), 'status': receipt['status']}))


if __name__ == '__main__':
    main()
