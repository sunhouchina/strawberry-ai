import os
import tempfile
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="strawberry-ai-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_DIR / 'test.db'}"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret"
os.environ["ACCESS_TOKEN_EXPIRE_SECONDS"] = "3600"
os.environ["OBJECT_STORAGE_ENDPOINT"] = "https://storage.example.test"
os.environ["OBJECT_STORAGE_BUCKET"] = "strawberry-images"
os.environ["OBJECT_STORAGE_ACCESS_KEY"] = "test-access-key"
os.environ["OBJECT_STORAGE_SECRET_KEY"] = "test-storage-secret"
os.environ["SIGNED_UPLOAD_EXPIRE_SECONDS"] = "300"
os.environ["UPLOAD_MAX_SIZE_BYTES"] = "5242880"

from app import config
from app.db import Base, SessionLocal, get_engine, get_session
from app.main import app
from app.models import User
from app.security import hash_password


def clear_settings_cache() -> None:
    config.database_url.cache_clear()
    config.jwt_secret_key.cache_clear()
    config.access_token_expire_seconds.cache_clear()
    config.object_storage_endpoint.cache_clear()
    config.object_storage_bucket.cache_clear()
    config.object_storage_access_key.cache_clear()
    config.object_storage_secret_key.cache_clear()
    config.signed_upload_expire_seconds.cache_clear()
    config.upload_max_size_bytes.cache_clear()
    config.allowed_upload_content_types.cache_clear()


clear_settings_cache()


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    clear_settings_cache()
    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())
    yield
    clear_settings_cache()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal(bind=get_engine())
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    def override_get_session() -> Generator[Session, None, None]:
        session = SessionLocal(bind=get_engine())
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def create_user(db_session: Session) -> Callable[[str, str, str], User]:
    def factory(username: str, password: str, role: str) -> User:
        user = User(username=username, password_hash=hash_password(password), role=role)
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return factory


@pytest.fixture
def login(client: TestClient) -> Callable[[str, str], dict[str, str]]:
    def factory(username: str, password: str) -> dict[str, str]:
        response = client.post(
            "/api/v1/auth/token",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        return {"Authorization": "Bearer " + token}

    return factory


@pytest.fixture
def refresh_settings() -> Callable[[], None]:
    return clear_settings_cache
