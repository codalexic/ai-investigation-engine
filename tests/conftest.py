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
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    from app.container import Container

    original = Container.build
    monkeypatch.setattr(
        Container,
        "build",
        lambda settings: original(
            Settings(
                _env_file=None,
                app_env="test",
                database_url=f"sqlite:///{tmp_path}/api.db",
                qdrant_collection="api_test",
            )
        ),
    )
    with TestClient(create_app()) as test_client:
        yield test_client
