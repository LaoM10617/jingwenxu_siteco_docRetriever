"""Startup and health behavior through the application interface."""

import socket
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def settings_for(path):
    return Settings(data_dir=path, gemini_api_key=None, groq_api_key=None, voyage_api_key=None)


def test_health_without_keys_or_network(tmp_path, monkeypatch):
    original_connect = socket.socket.connect
    def reject_network(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        pytest.fail("Startup and health must not contact external services")
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    with TestClient(create_app(settings_for(tmp_path / "runtime"))) as client:
        assert client.get("/api/health").json() == {"status": "ok", "version": "0.1.0"}
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/documents").status_code == 422


def test_startup_creates_storage_and_preserves_existing_database(tmp_path):
    runtime = tmp_path / "runtime"
    app = create_app(settings_for(runtime))
    assert not runtime.exists()
    with TestClient(app):
        assert (runtime / "app.sqlite3").is_file()
        assert not list(runtime.glob(".write-check-*"))
    with sqlite3.connect(runtime / "app.sqlite3") as connection:
        connection.execute("CREATE TABLE preserved (value TEXT)")
        connection.execute("INSERT INTO preserved VALUES ('retained')")
    with TestClient(create_app(settings_for(runtime))) as client:
        assert client.get("/api/health").status_code == 200
    with sqlite3.connect(runtime / "app.sqlite3") as connection:
        assert connection.execute("SELECT value FROM preserved").fetchone() == ("retained",)



def test_unwritable_directory_stops_startup(tmp_path, monkeypatch):
    import tempfile
    from app.main import StartupError
    def denied(*args, **kwargs):
        raise PermissionError("fixture-secret-path")
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", denied)
    with pytest.raises(StartupError, match="DATA_DIR") as caught:
        with TestClient(create_app(settings_for(tmp_path))):
            pytest.fail("Startup should stop")
    assert "fixture-secret-path" not in str(caught.value)


def test_corrupt_database_stops_startup_without_overwriting(tmp_path):
    from app.main import StartupError
    db = tmp_path / "app.sqlite3"
    db.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(StartupError, match="SQLite"):
        with TestClient(create_app(settings_for(tmp_path))):
            pytest.fail("Startup should stop")
    assert db.read_bytes() == b"not-a-sqlite-database"


def test_locked_database_stops_startup(tmp_path):
    from contextlib import closing
    from app.main import StartupError
    with closing(sqlite3.connect(tmp_path / "app.sqlite3")) as connection:
        connection.execute("CREATE TABLE existing (value TEXT)")
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(StartupError, match="SQLite"):
            with TestClient(create_app(settings_for(tmp_path))):
                pytest.fail("Startup should stop")
        connection.rollback()


def test_health_does_not_expose_configuration(tmp_path):
    configuration = settings_for(tmp_path)
    configuration.gemini_api_key = "fixture-secret"
    with TestClient(create_app(configuration)) as client:
        response = client.get("/api/health")
        assert set(response.json()) == {"status", "version"}
        assert "fixture-secret" not in response.text
        assert str(tmp_path) not in response.text
