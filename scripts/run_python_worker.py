"""Run on the trusted Docker host; never mount Docker into the backend."""
import argparse
import os
from pathlib import Path
import signal
import sys
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.host_worker import HostWorker, WorkerClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', default='http://127.0.0.1:8000')
    parser.add_argument('--work-dir', type=Path, default=Path('data/python-worker'))
    parser.add_argument('--image', required=True, help='Trusted runner image ID or repository@sha256:digest')
    parser.add_argument('--stop-file', type=Path,
                        help='Stop gracefully once this file exists (used by scripts/siteco.py)')
    args = parser.parse_args()
    token = os.environ.get('EXECUTION_WORKER_TOKEN', '')
    worker = HostWorker(args.work_dir, WorkerClient(args.backend, token), args.image)
    signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
    signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
    if args.stop_file:
        # A detached Windows process shares no console with the launcher, so console
        # signals cannot reach it; a file request works the same on every platform.
        def watch():
            while not worker.stop.wait(0.5):
                if args.stop_file.exists():
                    worker.stop.set()
        Thread(target=watch, daemon=True).start()
    worker.run()


if __name__ == '__main__':
    main()
