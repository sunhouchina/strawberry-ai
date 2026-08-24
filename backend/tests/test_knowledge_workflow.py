from app.models import AuditLog


def test_knowledge_workflow_and_public_gating(client, db_session, create_user, login):
    author = create_user("author1", "password123", "author")
    create_user("reviewer1", "password123", "reviewer")
    create_user("admin1", "password123", "admin")

    author_headers = login("author1", "password123")
    reviewer_headers = login("reviewer1", "password123")
    admin_headers = login("admin1", "password123")

    draft_response = client.post(
        "/api/v1/knowledge-documents",
        headers=author_headers,
        json={
            "title": "白粉病补拍流程",
            "source": "试点园区值班手册",
            "region": "江苏",
            "content": "发现白粉状症状时先补拍叶背，再检查棚室通风和湿度记录。",
            "metadata_json": {"stage": "flowering"},
        },
    )
    assert draft_response.status_code == 201
    document_id = draft_response.json()["id"]
    assert draft_response.json()["status"] == "draft"
    assert draft_response.json()["author_id"] == author.id

    public_before_review = client.get("/api/v1/knowledge-documents/public")
    assert public_before_review.status_code == 200
    assert public_before_review.json() == []

    premature_review = client.post(
        f"/api/v1/knowledge-documents/{document_id}/review",
        headers=reviewer_headers,
        json={"action": "approve", "review_notes": "先提交再审核"},
    )
    assert premature_review.status_code == 409

    submit_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/submit",
        headers=author_headers,
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["status"] == "pending_review"

    duplicate_submit = client.post(
        f"/api/v1/knowledge-documents/{document_id}/submit",
        headers=author_headers,
    )
    assert duplicate_submit.status_code == 409

    approve_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/review",
        headers=reviewer_headers,
        json={"action": "approve", "review_notes": "内容保守，适合公开引用。"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    public_after_approval = client.get(
        "/api/v1/knowledge-documents/public", params={"query": "白粉"}
    )
    assert public_after_approval.status_code == 200
    approved_documents = public_after_approval.json()
    assert [document["id"] for document in approved_documents] == [document_id]

    retire_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/retire",
        headers=admin_headers,
    )
    assert retire_response.status_code == 200
    assert retire_response.json()["status"] == "retired"

    public_after_retire = client.get("/api/v1/knowledge-documents/public")
    assert public_after_retire.status_code == 200
    assert public_after_retire.json() == []

    audit_actions = [
        entry.action
        for entry in db_session.query(AuditLog)
        .filter(AuditLog.entity_id == document_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    ]
    assert audit_actions == ["created", "submitted", "approved", "retired"]


def test_only_reviewers_can_see_other_authors_documents(client, create_user, login):
    create_user("author1", "password123", "author")
    create_user("author2", "password123", "author")
    create_user("reviewer1", "password123", "reviewer")

    first_author_headers = login("author1", "password123")
    second_author_headers = login("author2", "password123")
    reviewer_headers = login("reviewer1", "password123")

    response = client.post(
        "/api/v1/knowledge-documents",
        headers=first_author_headers,
        json={
            "title": "补拍果面",
            "source": "合作社内规",
            "content": "灰霉风险时要求补拍果面并隔离明显病果。",
        },
    )
    document_id = response.json()["id"]

    forbidden_response = client.get(
        f"/api/v1/knowledge-documents/{document_id}",
        headers=second_author_headers,
    )
    assert forbidden_response.status_code == 403

    reviewer_response = client.get(
        f"/api/v1/knowledge-documents/{document_id}",
        headers=reviewer_headers,
    )
    assert reviewer_response.status_code == 200


def test_safety_boundaries_block_storage_and_public_queries(client, create_user, login):
    create_user("author1", "password123", "author")
    author_headers = login("author1", "password123")

    blocked_create = client.post(
        "/api/v1/knowledge-documents",
        headers=author_headers,
        json={
            "title": "危险配比",
            "source": "未知来源",
            "content": "建议稀释比例 1:1000 后混配使用。",
        },
    )
    assert blocked_create.status_code == 422

    blocked_query = client.get(
        "/api/v1/knowledge-documents/public",
        params={"query": "采收安全期间隔期"},
    )
    assert blocked_query.status_code == 400
