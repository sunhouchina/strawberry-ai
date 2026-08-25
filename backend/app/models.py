import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def uuid_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Plot(Base):
    __tablename__ = "plots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    facility_type: Mapped[str | None] = mapped_column(String(100))


class CropCycle(Base):
    __tablename__ = "crop_cycles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plots.id"), nullable=False)
    variety: Mapped[str | None] = mapped_column(String(100))
    planting_date: Mapped[date | None] = mapped_column(Date)
    growth_stage: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="active")


class FarmingRecord(Base):
    __tablename__ = "farming_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    crop_cycle_id: Mapped[str] = mapped_column(ForeignKey("crop_cycles.id"), nullable=False)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="manual")


class FarmingInput(Base):
    __tablename__ = "farming_inputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    farming_record_id: Mapped[str] = mapped_column(ForeignKey("farming_records.id"), nullable=False)
    input_name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[str | None] = mapped_column(String(50))
    unit: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str | None] = mapped_column(String(50))


class CropObservation(Base):
    __tablename__ = "crop_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    crop_cycle_id: Mapped[str] = mapped_column(ForeignKey("crop_cycles.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    observed_part: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    image_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_assessment: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open")


class ExpertReview(Base):
    __tablename__ = "expert_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    observation_id: Mapped[str] = mapped_column(ForeignKey("crop_observations.id"), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_date: Mapped[date | None] = mapped_column(Date)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    region: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    review_notes: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    crop_cycle_id: Mapped[str] = mapped_column(ForeignKey("crop_cycles.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_value: Mapped[float] = mapped_column(nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class AIDecision(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    crop_cycle_id: Mapped[str] = mapped_column(ForeignKey("crop_cycles.id"), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="proposed", nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    crop_cycle_id: Mapped[str] = mapped_column(ForeignKey("crop_cycles.id"), nullable=False)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("ai_decisions.id"))
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    assigned_to_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_notes: Mapped[str | None] = mapped_column(Text)
    guardrail_state: Mapped[str] = mapped_column(String(30), default="normal", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class WorkOrderExecution(Base):
    __tablename__ = "work_order_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    work_order_id: Mapped[str] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    executor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    execution_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_notes: Mapped[str | None] = mapped_column(Text)
    anomaly_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class WorkOrderFeedback(Base):
    __tablename__ = "work_order_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    work_order_id: Mapped[str] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("ai_decisions.id"))
    metric_type: Mapped[str] = mapped_column(String(80), nullable=False)
    metric_value: Mapped[float] = mapped_column(nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recorded_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class DomainEvent(Base):
    __tablename__ = "domain_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
