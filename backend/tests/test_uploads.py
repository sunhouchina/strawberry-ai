from urllib.parse import parse_qs, urlparse

from conftest import create_user, login

VALID_SECRET = "ValidPass123"


def test_signed_upload_requires_configuration_and_authentication(client_factory):
    client = client_factory(storage_enabled=False)
    create_user(username="writer", secret=VALID_SECRET, role="author")

    unauthenticated = client.post(
        "/api/v1/uploads/image-instructions",
        json={"filename": "leaf.png", "content_type": "image/png", "size_bytes": 100},
    )
    assert unauthenticated.status_code == 401

    headers = login(client, username="writer", secret=VALID_SECRET)
    response = client.post(
        "/api/v1/uploads/image-instructions",
        headers=headers,
        json={"filename": "leaf.png", "content_type": "image/png", "size_bytes": 100},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Object storage upload is not configured."


def test_signed_upload_returns_scoped_constrained_instructions(client_factory):
    client = client_factory(storage_enabled=True)
    user = create_user(username="writer", secret=VALID_SECRET, role="author")
    headers = login(client, username="writer", secret=VALID_SECRET)

    response = client.post(
        "/api/v1/uploads/image-instructions",
        headers=headers,
        json={
            "filename": "../../../secret.png",
            "content_type": "image/png",
            "size_bytes": 1024,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["method"] == "PUT"
    assert payload["bucket"] == "knowledge-images"
    assert payload["max_size_bytes"] == 4096
    assert payload["allowed_content_types"] == ["image/jpeg", "image/png", "image/webp"]
    assert payload["object_key"].startswith(f"uploads/{user.id}/")
    assert ".." not in payload["object_key"]
    parsed = urlparse(payload["upload_url"])
    assert parsed.netloc == "storage.example.test"
    query = parse_qs(parsed.query)
    assert "signature" in query
    assert "expires" in query
    assert payload["headers"]["Content-Type"] == "image/png"
    assert payload["headers"]["x-strawberry-upload-owner"] == user.id


def test_signed_upload_enforces_size_and_content_type(client_factory):
    client = client_factory(storage_enabled=True)
    create_user(username="writer", secret=VALID_SECRET, role="author")
    headers = login(client, username="writer", secret=VALID_SECRET)

    invalid_type = client.post(
        "/api/v1/uploads/image-instructions",
        headers=headers,
        json={"filename": "leaf.gif", "content_type": "image/gif", "size_bytes": 100},
    )
    assert invalid_type.status_code == 400
    assert invalid_type.json()["detail"] == "Unsupported content type for image upload."

    too_large = client.post(
        "/api/v1/uploads/image-instructions",
        headers=headers,
        json={"filename": "leaf.png", "content_type": "image/png", "size_bytes": 5000},
    )
    assert too_large.status_code == 400
    assert too_large.json()["detail"] == "Image size exceeds the configured upload limit."
