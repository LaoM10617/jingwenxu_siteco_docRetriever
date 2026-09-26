"""Configuration behavior at the application loading interface."""

import os
from pathlib import Path
import socket

import pytest

from app.config import load_settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in list(os.environ):
        if name.upper() in {
            "APP_PORT", "DATA_DIR", "GEMINI_API_KEY", "GROQ_API_KEY",
            "VOYAGE_API_KEY", "GENERATION_PROVIDER", "GEMINI_GENERATION_MODEL",
            "GROQ_GENERATION_MODEL", "EMBEDDING_PROVIDER", "EMBEDDING_MODEL",
        }:
            monkeypatch.delenv(name)


def test_configuration_loads_without_keys_or_network(monkeypatch):
    def reject_network(*args, **kwargs):
        pytest.fail("Configuration must not connect to a provider")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    settings = load_settings(env_file=None)
    assert settings.app_port == 8000
    assert settings.gemini_api_key is None
    assert settings.groq_api_key is None
    assert settings.voyage_api_key is None


def test_explicit_dotenv_and_relative_data_path_ignore_working_directory(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[2]
    env_file = tmp_path / "local.env"
    env_file.write_text("APP_PORT=8100\nDATA_DIR=data/test-runtime\nGEMINI_API_KEY=fixture-key\n", encoding="utf-8")
    (tmp_path / ".env").write_text("APP_PORT=9999\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    relative_env = env_file
    settings = load_settings(env_file=relative_env)
    assert settings.app_port == 8100
    assert settings.data_dir == project_root / "data/test-runtime"
    assert settings.gemini_api_key.get_secret_value() == "fixture-key"
    monkeypatch.setenv("APP_PORT", "8200")
    assert load_settings(env_file=relative_env).app_port == 8200



@pytest.mark.parametrize("name,value", [
    ("APP_PORT", "0"), ("APP_PORT", "65536"), ("APP_PORT", "not-a-port-secret"),
    ("DATA_DIR", ""), ("DATA_DIR", "   "),
])
def test_invalid_configuration_reports_field_without_input(name, value, monkeypatch):
    from app.config import ConfigurationError
    monkeypatch.setenv(name, value)
    monkeypatch.setenv("GEMINI_API_KEY", "do-not-expose-secret")
    with pytest.raises(ConfigurationError) as caught:
        load_settings(env_file=None)
    assert name in str(caught.value)
    assert "do-not-expose-secret" not in str(caught.value)
    if value.strip():
        assert value not in str(caught.value)


def test_directory_cannot_be_a_file_or_descend_from_one(tmp_path, monkeypatch):
    from app.config import ConfigurationError
    file = tmp_path / "existing.txt"
    file.write_text("fixture", encoding="utf-8")
    for path in (file, file / "child"):
        monkeypatch.setenv("DATA_DIR", str(path))
        with pytest.raises(ConfigurationError, match="DATA_DIR"):
            load_settings(env_file=None)


def test_blank_keys_are_absent_and_present_keys_are_redacted(tmp_path):
    env_file = tmp_path / "keys.env"
    env_file.write_text('GEMINI_API_KEY=\nGROQ_API_KEY="   "\nVOYAGE_API_KEY=fixture-voyage-secret\n', encoding="utf-8")
    settings = load_settings(env_file)
    assert settings.gemini_api_key is None
    assert settings.groq_api_key is None
    assert settings.voyage_api_key.get_secret_value() == "fixture-voyage-secret"
    assert "fixture-voyage-secret" not in repr(settings)
    assert "fixture-voyage-secret" not in settings.model_dump_json()


def test_model_selection_comes_from_environment(monkeypatch):
    monkeypatch.setenv("GENERATION_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_GENERATION_MODEL", "openai/gpt-oss-120b")
    settings = load_settings(env_file=None)
    assert settings.generation_provider == "groq"
    assert settings.groq_generation_model == "openai/gpt-oss-120b"
    assert settings.embedding_provider == "voyage"
    assert settings.embedding_model == "voyage-4"


@pytest.mark.parametrize("name", ["GEMINI_GENERATION_MODEL", "GROQ_GENERATION_MODEL", "EMBEDDING_MODEL"])
def test_empty_model_name_is_rejected(name, monkeypatch):
    from app.config import ConfigurationError
    monkeypatch.setenv(name, "   ")
    with pytest.raises(ConfigurationError, match=name):
        load_settings(env_file=None)


def test_invalid_value_does_not_leak_through_traceback(monkeypatch):
    import traceback
    from app.config import ConfigurationError
    monkeypatch.setenv("GENERATION_PROVIDER", "fixture-secret-in-wrong-field")
    with pytest.raises(ConfigurationError) as caught:
        load_settings(env_file=None)
    assert "fixture-secret-in-wrong-field" not in "".join(traceback.format_exception(caught.value))


def test_explicit_dotenv_must_exist(tmp_path):
    from app.config import ConfigurationError
    with pytest.raises(ConfigurationError, match="dotenv"):
        load_settings(tmp_path / "missing.env")


def test_default_and_relative_dotenv_follow_project_location(tmp_path, monkeypatch):
    import runpy
    import shutil

    # Stage the same deployment layout with synthetic config; never edit real .env.
    root = tmp_path / "checkout"
    module_path = root / "backend/app/config.py"
    module_path.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / "app/config.py", module_path)
    (root / ".env").write_text("APP_PORT=8300\n", encoding="utf-8-sig")
    (root / "selected.env").write_text("APP_PORT=8400\n", encoding="utf-8")
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    (foreign / ".env").write_text("APP_PORT=9999\n", encoding="utf-8")
    monkeypatch.chdir(foreign)
    loader = runpy.run_path(str(module_path))["load_settings"]
    assert loader().app_port == 8300
    assert loader("selected.env").app_port == 8400
    assert loader(None).app_port == 8000
    (root / ".env").unlink()
    assert loader().app_port == 8000
    assert loader().data_dir == root / "data/runtime"
    assert not (root / "data/runtime").exists()
