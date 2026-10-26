from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("app.api.main.get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr("app.core.logging.get_settings", lambda: Settings(_env_file=None))
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client
