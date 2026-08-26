from conftest import create_user, login

VALID_SECRET = "ValidPass123"


def test_knowledge_workflow_requires_approval_for_public_search(client_factory):
    client = client_factory()
    create_user(username="writer", secret=VALID_SECRET, role="author")
    create_user(username="reviewer", secret=VALID_SECRET, role="reviewer")
    author_headers = login(client, username="writer", secret=VALID_SECRET)
    reviewer_headers = login(client, username="reviewer", secret=VALID_SECRET)

    create_response = client.post(
        "/api/v1/knowledge-documents",
        headers=author_headers,
        json={
            "title": "灰霉病补充排查",
            "body": "隔离明显病果，补拍灰色霉层，记录湿度与通风情况。",
            "source": "试点园区周报",
            "region": "江苏",
            "metadata_json": {"risk_level": "high"},
        },
    )
    assert create_response.status_code == 201
    document_id = create_response.json()["id"]

    search_before_approval = client.get("/api/v1/knowledge/search", params={"q": "灰霉"})
    assert search_before_approval.status_code == 200
    assert search_before_approval.json()["results"] == []

    submit_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/submit",
        headers=author_headers,
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["status"] == "submitted"
    assert submit_response.json()["submitted_at"] is not None

    approve_response = client.post(
        f"/api/v1/knowledge-documents/{document_id}/review",
        headers=reviewer_headers,
        json={"decision": "approved", "notes": "内容符合受控知识要求"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    assert approve_response.json()["reviewer_id"] is not None
    assert approve_response.json()["approved_at"] is not None

    search_after_approval = client.get("/api/v1/knowledge/search", params={"q": "灰霉"})
    assert search_after_approval.status_code == 200
    payload = search_after_approval.json()
    assert payload["blocked"] is False
    assert [item["id"] for item in payload["results"]] == [document_id]


def test_invalid_transition_and_author_visibility_are_enforced(client_factory):
    client = client_factory()
    author = create_user(username="writer", secret=VALID_SECRET, role="author")
    other_author = create_user(username="writer-2", secret=VALID_SECRET, role="author")
    reviewer = create_user(username="reviewer", secret=VALID_SECRET, role="reviewer")
    author_headers = login(client, username=author.username, secret=VALID_SECRET)
    other_author_headers = login(client, username=other_author.username, secret=VALID_SECRET)
    reviewer_headers = login(client, username=reviewer.username, secret=VALID_SECRET)

    create_response = client.post(
        "/api/v1/knowledge-documents",
        headers=author_headers,
        json={
            "title": "炭疽病补充记录",
            "body": "记录病斑扩展速度，并补充棚室和生育期信息。",
            "source": "县级植保站",
            "region": "浙江",
            "metadata_json": {"version": "2026-08"},
        },
    )
    document_id = create_response.json()["id"]

    unauthorized_read = client.get(
        f"/api/v1/knowledge-documents/{document_id}",
        headers=other_author_headers,
    )
    assert unauthorized_read.status_code == 403

    invalid_review = client.post(
        f"/api/v1/knowledge-documents/{document_id}/review",
        headers=reviewer_headers,
        json={"decision": "approved", "notes": "越过提交流程"},
    )
    assert invalid_review.status_code == 409
    assert invalid_review.json()["detail"] == "Only submitted documents can be reviewed."


def test_restricted_knowledge_requests_are_blocked(client_factory):
    client = client_factory()
    create_user(username="writer", secret=VALID_SECRET, role="author")
    headers = login(client, username="writer", secret=VALID_SECRET)

    create_response = client.post(
        "/api/v1/knowledge-documents",
        headers=headers,
        json={
            "title": "禁止存储的施药剂量",
            "body": "这里包含具体农药剂量和稀释比例。",
            "source": "不应录入",
            "region": "江苏",
            "metadata_json": {},
        },
    )

    assert create_response.status_code == 400
    assert "must not store pesticide dosage" in create_response.json()["detail"]

    search_response = client.get("/api/v1/knowledge/search", params={"q": "农药剂量"})
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["blocked"] is True
    assert payload["results"] == []
