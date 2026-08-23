import uuid
from datetime import date, datetime
from typing import Any
from sqlalchemy import Date, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


def uuid_id() -> str:
    return str(uuid.uuid4())


class Farm(Base):
    __tablename__ = "farms"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    reviewer_name: Mapped[str] = mapped_column(String(120), nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_id)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    region: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
