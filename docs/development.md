# Development setup

This guide covers the verified M0 development environment on Windows/PowerShell.
The application, frontend framework, backend web framework, model provider, parser,
and index dependencies have not been selected or installed yet.

## Verified toolchain

Checked on 2026-09-26:

- Python 3.12.10 (independent Windows installation), with an isolated `backend/.venv` and pip 25.0.1.
- Node.js 24.19.0 and npm 11.17.0.
- Docker Desktop 4.92.0, Docker Engine/CLI 29.8.0, Compose v5.5.1.
- WSL 2.7.14.0; `docker-desktop` runs as a WSL 2 distribution.
- Docker runs Linux/amd64 containers with a WSL 2 kernel.

Python 3.12 is the confirmed project version. Other tool versions above describe
what was tested, rather than claiming that every listed patch version is required.
No application dependency compatibility or application container build has been
verified yet.

## Starting directory

Run the commands below from the repository root, the directory containing this
file's parent `docs/` directory, `backend/`, and `frontend/`.

After repository access and the first push are available, a new checkout can use:

```powershell
git clone https://github.com/LaoM10617/jingwenxu_siteco_docRetriever.git
cd jingwenxu_siteco_docRetriever
```

The remote is currently private and empty. Cloning it today will not reproduce
this working tree until the separately approved push. The first local commit is authorized.

## Docker and WSL 2

Start Docker Desktop and wait for its Linux engine to become available. Verify:

```powershell
wsl --version
wsl --list --verbose
docker version
docker compose version
docker info --format '{{.OSType}} {{.Architecture}} {{.KernelVersion}}'
docker run --rm hello-world
```

Expected results: both Client and Server are present; the OS is `linux`; the
Docker WSL distribution uses version 2; the container prints `Hello from Docker!`.
The last command may download an image and removes the test container on exit.
It leaves the downloaded image cached.

### Existing terminal cannot find Docker

The current machine uses a per-user Docker Desktop installation. Its CLI directory
is already in the saved user PATH, but the existing Codex process has an older
PATH. Open a fresh terminal from a refreshed parent process, or restart Codex.
For a per-user installation, the following session-only fallback was validated:

```powershell
$dockerBin = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin'
$env:Path = "$dockerBin;$env:Path"
docker version
```

This does not modify the persistent PATH. For other installations, use the actual
Docker CLI directory. No Docker reinstall or WSL reset is needed for this case.
Ubuntu integration is not needed for this PowerShell workflow.

## Python 3.12 environment

Install an independent 64-bit Python 3.12 distribution before creating the
project environment. Do not copy another project's environment or use a Codex
cache as the base interpreter.

The verified Windows installation uses the signed Python Software Foundation
[Python 3.12.10 installer](https://www.python.org/downloads/release/python-31210/).
This is the last 3.12 release with traditional Windows binary installers, not the
latest security patch release. [Python 3.12.14](https://www.python.org/downloads/release/python-31214/)
is newer and contains security fixes. The move from the bundled 3.12.14 to the
independent 3.12.10 is recorded explicitly; dependency and final Docker runtime
compatibility still need validation. Do not treat the local patch version as a
requirement to use an older patch in the delivered container.

Install for the current user in `%LOCALAPPDATA%/Programs/Python/Python312`, with
pip enabled. Keep an existing Windows Python launcher. The current setup leaves
PATH and file associations unchanged, so the global `python` remains 3.14.7.
The installer registers the new interpreter for `py -3.12`.

For unattended reproduction of the current installation, download the 64-bit
installer from the release page, verify that its Authenticode signature is valid
and signed by the Python Software Foundation, and use these installer options:

```text
/quiet InstallAllUsers=0 TargetDir="<LOCALAPPDATA>/Programs/Python/Python312" PrependPath=0 AssociateFiles=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_pip=1 Shortcuts=0
```

Replace `<LOCALAPPDATA>` with the actual user installation directory. These
options assume a Windows Python launcher is already installed. A fresh machine
without one should include the launcher during installation or invoke the new
Python executable by its full path.

From the repository root, create and verify the environment:

```powershell
py -3.12 --version
py -3.12 -c "import sys; print(sys.executable)"
py -3.12 -m venv backend/.venv
& ./backend/.venv/Scripts/python.exe --version
& ./backend/.venv/Scripts/python.exe -m pip --version
& ./backend/.venv/Scripts/python.exe -m pip check
& ./backend/.venv/Scripts/python.exe -c "import sys; assert sys.version_info[:2] == (3, 12); assert sys.prefix != sys.base_prefix; print('Base:', sys.base_prefix); print('Python 3.12 virtual environment OK')"
```

The base path must point to the independent Python installation, not a Codex
cache. Activation is optional because commands explicitly use the environment.
The verified environment contains pip 25.0.1 only. Standard-library imports of
`ssl`, `sqlite3`, and `venv` passed; no application packages are installed yet.

To rebuild, close processes using this environment, confirm the absolute target
is this checkout's `backend/.venv`, remove only that directory, then repeat the
commands above. Do not edit `pyvenv.cfg` to change interpreters. The environment
is ignored by Git. It still depends on the independent base installation, which
should be maintained separately from application dependencies.

## Node.js and npm

```powershell
node --version
npm --version
node -e "const assert=require('node:assert/strict'); assert.equal(JSON.parse(JSON.stringify({ok:true})).ok,true); console.log('Node runtime check passed')"
```

These commands passed on the current machine. There is no frontend `package.json`
or lockfile yet, so no `npm install`, `npm ci`, or frontend build has been run.
Add and commit the package manifest and lockfile after the frontend is selected;
then record and verify its installation and build commands here.

## Configuration and subsequent dependencies

- No model credentials or environment variables are required for these checks.
- `.env.example` remains empty until real configuration is defined.
- Add the web framework, parser, model SDK, retrieval packages, and test tools only
  when the relevant choices and test boundaries are confirmed.
- Record direct dependencies and reproducible versions as dependencies are added;
  no empty dependency files or speculative packages are needed now.
- `.dockerignore` is still empty. Define it before the first project Docker build.
  The successful `hello-world` run is an engine check, not application packaging.

## Verification boundary

Passed: Docker client/server and Compose, actual Linux container execution,
Node/npm availability, isolated Python 3.12 environment, pip integrity, basic
standard-library imports, and Git exclusion of the virtual environment.

Not yet verified: package-registry installation for the application, application
dependencies, model connectivity, frontend build, project Docker build, or the
upload-to-answer flow. Reproduction from committed source remains pending the
first approved commit/push and subsequent application implementation.
