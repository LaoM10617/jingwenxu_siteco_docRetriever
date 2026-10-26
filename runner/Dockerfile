FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
# requirements.lock is exported from runner/uv.lock with hashes (ADR 0007); CI checks they match.
COPY runner/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /tmp/requirements.lock \
    && pip check && rm /tmp/requirements.lock
COPY backend/app/csv_runtime.py /usr/local/lib/python3.12/site-packages/siteco_analysis.py
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
USER 65534:65534
WORKDIR /tmp
