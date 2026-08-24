def test_upload_instructions_require_authentication(client):
    response = client.post(
        "/api/v1/uploads/image-instructions",
        json={
            "filename": "leaf.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 1024,
        },
    )

    assert response.status_code == 401


def test_upload_instructions_return_scoped_constraints(client, create_user, login):
    user = create_user("author1", "password123", "author")
    headers = login("author1", "password123")

    response = client.post(
        "/api/v1/uploads/image-instructions",
        headers=headers,
        json={
            "filename": "leaf.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 1024,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "POST"
    assert payload["max_size_bytes"] == 5242880
    assert payload["object_key"].startswith(f"uploads/{user.id}/")
    assert payload["fields"]["content_type"] == "image/jpeg"
    assert payload["fields"]["key"] == payload["object_key"]


def test_upload_instructions_reject_invalid_type_and_size(client, create_user, login):
    create_user("author1", "password123", "author")
    headers = login("author1", "password123")

    type_response = client.post(
        "/api/v1/uploads/image-instructions",
        headers=headers,
        json={
            "filename": "leaf.gif",
            "content_type": "image/gif",
            "size_bytes": 1024,
        },
    )
    assert type_response.status_code == 422

    size_response = client.post(
        "/api/v1/uploads/image-instructions",
        headers=headers,
        json={
            "filename": "leaf.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 6000000,
        },
    )
    assert size_response.status_code == 422


def test_upload_instructions_fail_safely_without_storage_config(
    client,
    create_user,
    login,
    monkeypatch,
    refresh_settings,
):
    create_user("author1", "password123", "author")
    headers = login("author1", "password123")
    monkeypatch.delenv("OBJECT_STORAGE_SECRET_KEY", raising=False)
    refresh_settings()

    response = client.post(
        "/api/v1/uploads/image-instructions",
        headers=headers,
        json={
            "filename": "leaf.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 1024,
        },
    )

    assert response.status_code == 503
