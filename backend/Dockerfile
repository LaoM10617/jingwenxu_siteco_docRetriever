# Verified Python 3.12.14 / Debian 12 bookworm; digest pins the fetched base.
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/runtime
WORKDIR /app
COPY backend/requirements.lock.txt /app/backend/requirements.lock.txt
RUN python -m pip install --no-cache-dir -r backend/requirements.lock.txt \
    && python -m pip check \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/runtime \
    && chown app:app /app/runtime

# Explicit test target; its packages and fixtures do not enter the runtime image.
FROM dependencies AS test
COPY backend/requirements-dev.lock.txt /app/backend/requirements-dev.lock.txt
RUN python -m pip install --no-cache-dir -r backend/requirements-dev.lock.txt \
    && python -m pip check
COPY backend/app /app/backend/app
COPY backend/tests /app/backend/tests
COPY tests/test_tracing.py /app/tests/test_tracing.py
COPY pytest.ini /app/pytest.ini
USER 10001:10001
RUN python -m pytest -q -p no:cacheprovider

FROM dependencies AS runtime
COPY backend/app /app/backend/app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).close()"]
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
