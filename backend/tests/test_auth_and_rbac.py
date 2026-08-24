from conftest import create_user, login

from app.auth import create_access_token

VALID_SECRET = "ValidPass123"


def test_login_requires_valid_credentials(client_factory):
    client = client_factory()
    create_user(username="writer", secret=VALID_SECRET, role="author")

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "writer", "password": "wrong-pass-1"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


def test_me_requires_authentication(client_factory):
    client = client_factory()

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_expired_token_is_rejected(client_factory):
    client = client_factory()
    user = create_user(username="writer", secret=VALID_SECRET, role="author")
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        expires_in_minutes=-1,
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})

    assert response.status_code == 401
    assert response.json()["detail"] == "Access token has expired."


def test_rbac_blocks_author_from_reviewing_documents(client_factory):
    client = client_factory()
    create_user(username="writer", secret=VALID_SECRET, role="author")
    create_user(username="reviewer", secret=VALID_SECRET, role="reviewer")
    headers = login(client, username="writer", secret=VALID_SECRET)

    create_response = client.post(
        "/api/v1/knowledge-documents",
        headers=headers,
        json={
            "title": "白粉病识别",
            "body": "检查叶背和通风条件，记录白色粉状斑位置。",
            "source": "合作社技术规范",
            "region": "江苏",
            "metadata_json": {"growth_stage": "花期"},
        },
    )
    document_id = create_response.json()["id"]
    submit_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/submit",
        headers=headers,
    )
    assert submit_response.status_code == 200

    review_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/review",
        headers=headers,
        json={"decision": "approved", "notes": "允许发布"},
    )

    assert review_response.status_code == 403
    assert review_response.json()["detail"] == "You do not have permission to perform this action."
