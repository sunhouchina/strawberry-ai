from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.auth import hash_password
from app.config import reset_settings_cache
from app.db import get_session_factory, reset_db_cache
from app.main import create_app
from app.models import User


@pytest.fixture
def client_factory(monkeypatch, tmp_path_factory):
    clients: list[TestClient] = []

    def make_client(*, storage_enabled: bool = False) -> TestClient:
        db_dir = tmp_path_factory.mktemp("db")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_dir / 'test.db'}")
        monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret")
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRES_MINUTES", "30")
        if storage_enabled:
            monkeypatch.setenv("STORAGE_BUCKET", "knowledge-images")
            monkeypatch.setenv("STORAGE_ENDPOINT_BASE", "https://storage.example.test")
            monkeypatch.setenv("STORAGE_SIGNING_SECRET", "storage-test-secret")
            monkeypatch.setenv("STORAGE_UPLOAD_TTL_SECONDS", "120")
            monkeypatch.setenv("STORAGE_MAX_UPLOAD_BYTES", "4096")
        else:
            monkeypatch.delenv("STORAGE_BUCKET", raising=False)
            monkeypatch.delenv("STORAGE_ENDPOINT_BASE", raising=False)
            monkeypatch.delenv("STORAGE_SIGNING_SECRET", raising=False)
            monkeypatch.delenv("STORAGE_UPLOAD_TTL_SECONDS", raising=False)
            monkeypatch.delenv("STORAGE_MAX_UPLOAD_BYTES", raising=False)
        reset_settings_cache()
        reset_db_cache()
        client = TestClient(create_app())
        client.__enter__()
        clients.append(client)
        return client

    yield make_client

    for client in clients:
        client.__exit__(None, None, None)
    reset_settings_cache()
    reset_db_cache()


def create_user(*, username: str, secret: str, role: str) -> User:
    user = User(username=username, password_hash=hash_password(secret), role=role)
    with get_session_factory()() as session:
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def login(client: TestClient, *, username: str, secret: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": secret},
    )
    assert response.status_code == 200, response.text
    access_token = response.json()["access_token"]
    return {"Authorization": "Bearer " + access_token}
