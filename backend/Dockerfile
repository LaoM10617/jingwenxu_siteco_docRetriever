# Verified Python 3.12.14 / Debian 12 bookworm; digest pins the fetched base.
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/runtime \
    PYTHONPATH=/app/backend \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock /app/
# uv is mounted only for the install (ADR 0007): version and digest match [tool.uv] required-version.
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a,source=/uv,target=/bin/uv \
    uv sync --locked --no-dev \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/runtime \
    && chown app:app /app/runtime

# Explicit test target; its packages and fixtures do not enter the runtime image.
FROM dependencies AS test
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a,source=/uv,target=/bin/uv \
    uv sync --locked
COPY backend/app /app/backend/app
COPY backend/tests /app/backend/tests
COPY tests/test_tracing.py /app/tests/test_tracing.py
COPY pytest.ini /app/pytest.ini
USER 10001:10001
RUN python -m pytest -q -p no:cacheprovider

FROM dependencies AS runtime
COPY backend/app /app/backend/app
# Set by scripts/siteco.py; declared last so a new value only rebuilds this layer.
ARG BUILD_FINGERPRINT=dev
ENV BUILD_FINGERPRINT=$BUILD_FINGERPRINT
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).close()"]
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
