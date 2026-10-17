import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch):
    # Settings reads the process environment; a developer shell often carries real
    # provider keys or worker settings, which turned "missing key" tests into
    # environment-dependent failures. Tests must only see values they set themselves.
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
