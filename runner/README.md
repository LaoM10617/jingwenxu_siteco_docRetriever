# CSV execution worker

Build the Linux/amd64 pandas runner from the repository root:

```powershell
docker build -t siteco-csv-runner:local -f runner/Dockerfile .
docker image inspect --format '{{.Id}}' siteco-csv-runner:local
```

Set backend `EXECUTION_IMAGE` to that complete `sha256:...` identity and
`EXECUTION_WORKER_TOKEN` to a generated secret. Set the same token in the trusted
host process environment (not a frontend variable or a command-line argument).
The backend may read its project-root `.env`; the worker reads the token only
from its environment. Do not print the token in logs or save it in this repository.

Start the backend using the normal local or Compose deployment procedure, then
run the worker on the Docker host with the backend's loopback published port:

```powershell
.venv/Scripts/python.exe scripts/run_python_worker.py --backend http://127.0.0.1:8000 --work-dir data/python-worker --image sha256:YOUR_IMAGE_ID
```

Use a persistent, instance-specific work directory. The worker locks that directory,
recovers only its labelled containers, and retains delivery receipts across restart.
It never automatically reruns interrupted computation. Resume the conversation run
explicitly; successful model responses and execution results are reused where valid.
Failed CSV tasks can be retried by explicit resume within a fresh bounded attempt.
Only the worker has Docker access. Remote worker connections require HTTPS;
local plain HTTP is limited to loopback. Do not expose the bearer endpoint without
transport protection or mount a Docker socket in the backend.

The backend and worker must use the same image identity. Rebuild after changing
`csv_runtime.py` or the lock, then update both configurations. Saved runs retain their
execution image in their behavior snapshot, so changing it requires a new request
or restoring the original configuration before resume.

Inputs are complete authorized snapshots. Each one-shot container runs with no
network, read-only root/input mounts, non-root user, dropped capabilities, 1 CPU,
256 MiB memory, 64 PIDs, and fixed BLAS thread limits. Execution is limited to
30 seconds and 16 MiB combined output; graph/model deadlines are separate. Results
are bounded JSON (20,000 rows / 100 columns / 16 MiB), stored in business SQLite;
large-file export and automatic background exploration are later work.

Validation:

```powershell
$env:SITECO_DOCKER_TESTS='1'
$env:SITECO_RUNNER_IMAGE='sha256:YOUR_IMAGE_ID'
.venv/Scripts/python.exe -m pytest -q backend/tests/test_python_executor.py backend/tests/test_csv_runtime_docker.py
.venv/Scripts/python.exe scripts/probe_stage_d_analysis.py --image $env:SITECO_RUNNER_IMAGE
```

The last command makes small real Gemini requests using existing backend credentials,
creates an independent runtime below `data/stage-d`, and leaves existing deployments
untouched. Its receipt distinguishes actual model execution from deterministic tests.
