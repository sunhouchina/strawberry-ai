from datetime import UTC, datetime, timedelta

from conftest import create_user, login
from sqlalchemy import select

from app.db import get_session_factory
from app.models import CropCycle, DomainEvent, Farm, Plot

VALID_SECRET = "ValidPass123"


def _create_cycle() -> str:
    farm = Farm(name="试点农场", region="江苏")
    with get_session_factory()() as session:
        session.add(farm)
        session.flush()
        plot = Plot(farm_id=farm.id, name="A3棚", facility_type="greenhouse")
        session.add(plot)
        session.flush()
        cycle = CropCycle(plot_id=plot.id, variety="红颜", growth_stage="开花期")
        session.add(cycle)
        session.commit()
        session.refresh(cycle)
        return cycle.id


def test_closed_loop_flow_with_high_risk_review_gate(client_factory):
    client = client_factory()
    create_user(username="writer", secret=VALID_SECRET, role="author")
    create_user(username="reviewer", secret=VALID_SECRET, role="reviewer")
    author_headers = login(client, username="writer", secret=VALID_SECRET)
    reviewer_headers = login(client, username="reviewer", secret=VALID_SECRET)
    cycle_id = _create_cycle()
    now = datetime.now(UTC)

    sensor_response = client.post(
        "/api/v1/sensor-readings",
        headers=author_headers,
        json={
            "crop_cycle_id": cycle_id,
            "observed_at": now.isoformat(),
            "source_type": "device",
            "metric_key": "substrate_moisture",
            "metric_value": 60.2,
            "unit": "%",
            "metadata_json": {"device_id": "sensor-01"},
        },
    )
    assert sensor_response.status_code == 201, sensor_response.text

    decision_response = client.post(
        "/api/v1/decisions/water-fertilizer",
        headers=author_headers,
        json={
            "crop_cycle_id": cycle_id,
            "target_date": (now + timedelta(hours=2)).isoformat(),
            "check_items": ["检查阀门状态"],
        },
    )
    assert decision_response.status_code == 201, decision_response.text
    decision_payload = decision_response.json()
    assert decision_payload["decision_type"] == "water_fertilizer"
    assert decision_payload["recommendation_json"]["irrigation_plan"]

    work_order_response = client.post(
        "/api/v1/work-orders/plant-protection",
        headers=author_headers,
        json={
            "crop_cycle_id": cycle_id,
            "title": "疑似灰霉病高风险处置",
            "risk_level": "high",
            "due_at": (now + timedelta(hours=8)).isoformat(),
            "recommendation": "先隔离明显病果并补充叶背和果实照片，提交农技员复核。",
            "follow_up_date": (now + timedelta(days=1)).isoformat(),
            "check_items": ["上传复查照片", "记录通风和湿度"],
        },
    )
    assert work_order_response.status_code == 201, work_order_response.text
    work_order = work_order_response.json()
    assert work_order["status"] == "pending_review"
    assert work_order["requires_review"] is True

    blocked_execution = client.post(
        f"/api/v1/work-orders/{work_order['id']}/executions",
        headers=author_headers,
        json={
            "execution_mode": "manual",
            "executed_at": now.isoformat(),
            "evidence_refs": ["obs://image/001"],
            "result_notes": "待审核前禁止执行",
            "anomaly_json": {},
            "mark_completed": False,
        },
    )
    assert blocked_execution.status_code == 409
    assert blocked_execution.json()["detail"] == "Work order is pending reviewer approval."

    review_response = client.post(
        f"/api/v1/work-orders/{work_order['id']}/review",
        headers=reviewer_headers,
        json={"decision": "approved", "notes": "允许执行并要求回传"},
    )
    assert review_response.status_code == 200, review_response.text
    reviewed = review_response.json()
    assert reviewed["status"] == "open"
    assert reviewed["reviewer_id"] is not None

    execution_response = client.post(
        f"/api/v1/work-orders/{work_order['id']}/executions",
        headers=author_headers,
        json={
            "execution_mode": "manual",
            "executed_at": (now + timedelta(hours=1)).isoformat(),
            "evidence_refs": ["obs://image/002"],
            "result_notes": "已执行隔离并补拍",
            "anomaly_json": {"humidity_spike": True},
            "mark_completed": True,
        },
    )
    assert execution_response.status_code == 201, execution_response.text

    feedback_response = client.post(
        f"/api/v1/work-orders/{work_order['id']}/feedback",
        headers=author_headers,
        json={
            "metric_type": "disease_recurrence_rate",
            "metric_value": 0.1,
            "unit": "ratio",
            "notes": "24小时复查未扩散",
            "metadata_json": {"window_hours": 24},
            "recorded_at": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert feedback_response.status_code == 201, feedback_response.text

    with get_session_factory()() as session:
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.entity_id == work_order["id"])
        ).all()
    assert events


def test_plant_protection_recommendation_blocks_restricted_content(client_factory):
    client = client_factory()
    create_user(username="writer", secret=VALID_SECRET, role="author")
    author_headers = login(client, username="writer", secret=VALID_SECRET)
    cycle_id = _create_cycle()
    now = datetime.now(UTC)

    response = client.post(
        "/api/v1/work-orders/plant-protection",
        headers=author_headers,
        json={
            "crop_cycle_id": cycle_id,
            "title": "非法剂量建议",
            "risk_level": "high",
            "due_at": now.isoformat(),
            "recommendation": "建议农药剂量每亩50毫升并按比例混配。",
            "follow_up_date": (now + timedelta(days=1)).isoformat(),
            "check_items": [],
        },
    )
    assert response.status_code == 400
    assert "cannot include dosage or mixing details" in response.json()["detail"]
