# Development setup

M0 provides three standalone migrated modules, one tracing test file, and a
minimal Python dependency set. It is not a running document-chat application.

## Verified environment (2026-09-26)

- Windows x64, independent Python 3.12.10, pip 25.0.1.
- rank-bm25 0.2.2 and its NumPy 2.5.3 dependency.
- Node.js 24.19.0 and npm 11.17.0.
- Docker Desktop 4.92.0, Engine/CLI 29.8.0, Compose v5.5.1.
- WSL 2.7.14.0, docker-desktop distribution using WSL 2, Linux/amd64 containers.

Python 3.12 is the confirmed project version. Other versions identify the tested
setup. Linux dependency installation and the application Docker image remain unverified.

## Checkout

Access to the private repository is required:

```powershell
git clone https://github.com/LaoM10617/jingwenxu_siteco_docRetriever.git
cd jingwenxu_siteco_docRetriever
```

Run subsequent commands from the repository root. Empty directories shown in the
planned README structure are not tracked by Git and can be created when needed.

## Independent Python installation

Use an independent 64-bit Python 3.12 installation, not a copied virtual environment
or a Codex cache. This machine uses the signed Python Software Foundation
[3.12.10 Windows installer](https://www.python.org/downloads/release/python-31210/),
installed for the current user in `%LOCALAPPDATA%/Programs/Python/Python312`.
Its Authenticode signature was validated before installation.

3.12.10 is the last release with traditional Windows installers, not the latest
security patch. [3.12.14](https://www.python.org/downloads/release/python-31214/)
is newer. The local patch version does not require the delivered container to use
an older patch; select and validate the container runtime separately.

The installer options used were:

```text
/quiet InstallAllUsers=0 TargetDir="<LOCALAPPDATA>/Programs/Python/Python312" PrependPath=0 AssociateFiles=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_pip=1 Shortcuts=0
```

Replace `<LOCALAPPDATA>` with the user installation directory. These options keep
an existing Python launcher, PATH and file associations. On a fresh machine,
include the launcher or use the interpreter's full path. Global `python` remains
3.14.7 on this machine; explicitly select 3.12 for the project.

## Create the environment and install dependencies

```powershell
py -3.12 --version
py -3.12 -c "import sys; print(sys.executable)"
py -3.12 -m venv backend/.venv
& ./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
& ./backend/.venv/Scripts/python.exe -m pip check
& ./backend/.venv/Scripts/python.exe -c "import sys; assert sys.version_info[:2] == (3, 12); assert sys.prefix != sys.base_prefix; print('Base:', sys.base_prefix)"
```

The base must be the independent Python installation. Activation is optional.
`backend/requirements.txt` declares direct dependencies; the lock file pins the
runtime and transitive packages validated on Windows x64 / Python 3.12.10.
Do not install the old project's full dependency list.

To rebuild, stop processes using this project's environment, verify the absolute
path is this checkout's `backend/.venv`, remove only that directory, and repeat
the commands above. Do not modify `pyvenv.cfg` to switch interpreters. The venv is
ignored by Git and depends on the independent base installation.

## Check the migrated modules

```powershell
& ./backend/.venv/Scripts/python.exe -B tests/test_tracing.py
& ./backend/.venv/Scripts/python.exe -B -c "import sys; sys.path.insert(0, 'backend'); from app.retrieval.fusion import reciprocal_rank_fusion; assert reciprocal_rank_fusion([['a','b'],['b','c']]) == ['b','a','c']; print('Fusion smoke check passed')"
& ./backend/.venv/Scripts/python.exe -B -c "import sys; sys.path.insert(0, 'backend'); from app.retrieval.lexical import BM25Index; i=BM25Index(); i.replace_documents([('a','LED-100 Leuchte')]); assert i.search('LED-100',5)==['a']; i.replace_documents([('a','Leuchte'),('b','Sensor')]); assert i.search('Sensor',5)==['b']; assert i.search('unknown',5)==[]; print('Lexical smoke check passed')"
```

The tracing file contains 10 unittest cases. Fusion/lexical formal tests are
explicitly deferred until subsequent implementation. Their smoke checks do not
establish retrieval quality, document-scope integration or end-to-end behavior.
Callers must filter document scope before the final top_k selection.

## Docker and WSL 2

Start Docker Desktop and wait for its Linux engine, then run:

```powershell
wsl --version
wsl --list --verbose
docker version
docker compose version
docker info --format '{{.OSType}} {{.Architecture}} {{.KernelVersion}}'
docker run --rm hello-world
```

Earlier environment verification passed: Client and Server available, Linux
containers, WSL 2 and `Hello from Docker!`. The command may download the test
image; the container is removed on exit and the image remains cached.

The current Codex process may have an older PATH than the saved user PATH. For
this per-user installation, a validated session-only fallback is:

```powershell
$dockerBin = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin'
$env:Path = "$dockerBin;$env:Path"
docker version
```

Alternatively, restart the terminal's parent application. No permanent PATH or
WSL changes are required. Ubuntu integration is not needed for PowerShell use.

## Node.js and npm

```powershell
node --version
npm --version
node -e "const assert=require('node:assert/strict'); assert.equal(JSON.parse(JSON.stringify({ok:true})).ok,true); console.log('Node runtime check passed')"
```

These passed during environment setup. No frontend package manifest exists yet;
no frontend install or build has been performed. Add the manifest and lockfile
when the frontend is selected.

## Deferred configuration and validation

- No model credentials are needed for the migrated modules. `.env.example` is empty.
- Select web frameworks, parser and model SDK later; only add confirmed dependencies.
- `.dockerignore` is empty; complete it before the first project image build.
- The API server, upload UI, application Docker image and model integration do not exist yet.
- Linux dependency compatibility, fusion/lexical formal suites and the upload-to-answer
  flow remain later milestone work. Docker hello-world is not application packaging.
