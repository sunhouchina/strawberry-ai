def test_login_returns_jwt_and_current_user(client, create_user, login):
    create_user("author1", "password123", "author")

    token_response = client.post(
        "/api/v1/auth/token",
        json={"username": "author1", "password": "password123"},
    )

    assert token_response.status_code == 200
    payload = token_response.json()
    assert payload["token_type"] == "bearer"
    assert payload["role"] == "author"
    assert payload["expires_in"] == 3600

    me_response = client.get("/api/v1/auth/me", headers=login("author1", "password123"))

    assert me_response.status_code == 200
    assert me_response.json()["username"] == "author1"


def test_login_rejects_invalid_credentials(client, create_user):
    create_user("author1", "password123", "author")

    response = client.post(
        "/api/v1/auth/token",
        json={"username": "author1", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_protected_endpoints_require_authentication(client):
    response = client.post(
        "/api/v1/knowledge-documents",
        json={
            "title": "通风管理",
            "source": "合作社内规",
            "content": "仅记录补拍和复核建议。",
        },
    )

    assert response.status_code == 401


def test_author_cannot_review_documents(client, create_user, login):
    create_user("author1", "password123", "author")
    headers = login("author1", "password123")
    document_response = client.post(
        "/api/v1/knowledge-documents",
        headers=headers,
        json={
            "title": "叶背补拍要求",
            "source": "合作社内规",
            "content": "发现白粉状症状时要求补拍叶背并记录棚室湿度。",
        },
    )
    document_id = document_response.json()["id"]

    submit_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/submit",
        headers=headers,
    )

    assert submit_response.status_code == 200

    review_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/review",
        headers=headers,
        json={"action": "approve", "review_notes": "通过"},
    )

    assert review_response.status_code == 403
