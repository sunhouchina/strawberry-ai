from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import create_access_token, verify_password
from app.config import get_settings
from app.db import get_session, init_db
from app.models import (
    AIDecision,
    AuditLog,
    CropCycle,
    DomainEvent,
    KnowledgeDocument,
    SensorReading,
    User,
    WorkOrder,
    WorkOrderExecution,
    WorkOrderFeedback,
)
from app.security import get_current_user, require_roles
from app.storage import build_signed_upload_instruction

AUTHOR_ROLE = "author"
REVIEWER_ROLE = "reviewer"
ADMIN_ROLE = "admin"
DOCUMENT_DRAFT = "draft"
DOCUMENT_SUBMITTED = "submitted"
DOCUMENT_APPROVED = "approved"
DOCUMENT_REJECTED = "rejected"
DOCUMENT_RETIRED = "retired"
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_BLOCKED = "blocked"
WORK_ORDER_PENDING_REVIEW = "pending_review"
WORK_ORDER_OPEN = "open"
WORK_ORDER_IN_PROGRESS = "in_progress"
WORK_ORDER_COMPLETED = "completed"
WORK_ORDER_CANCELLED = "cancelled"
WORK_ORDER_REJECTED = "rejected"
RESTRICTED_KNOWLEDGE_TERMS = (
    "农药",
    "剂量",
    "配比",
    "稀释",
    "混配",
    "采收安全",
    "安全间隔",
    "间隔期",
)
session_dependency = Depends(get_session)
current_user_dependency = Depends(get_current_user)
author_access_dependency = Depends(require_roles(AUTHOR_ROLE, REVIEWER_ROLE, ADMIN_ROLE))
reviewer_access_dependency = Depends(require_roles(REVIEWER_ROLE, ADMIN_ROLE))
admin_access_dependency = Depends(require_roles(ADMIN_ROLE))


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class UserResponse(BaseModel):
    id: str
    username: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=300)
    region: str | None = Field(default=None, max_length=200)
    metadata_json: dict = Field(default_factory=dict)


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1)
    source: str | None = Field(default=None, min_length=1, max_length=300)
    region: str | None = Field(default=None, max_length=200)
    metadata_json: dict | None = None


class KnowledgeReviewRequest(BaseModel):
    decision: str
    notes: str | None = None


class KnowledgeDocumentResponse(BaseModel):
    id: str
    title: str
    body: str
    source: str
    region: str | None
    status: str
    author_id: str
    reviewer_id: str | None
    review_notes: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    approved_at: datetime | None
    rejected_at: datetime | None
    retired_at: datetime | None
    status_changed_at: datetime
    metadata_json: dict
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeSearchResult(BaseModel):
    id: str
    title: str
    source: str
    region: str | None
    excerpt: str


class KnowledgeSearchResponse(BaseModel):
    blocked: bool = False
    message: str | None = None
    results: list[KnowledgeSearchResult]


class UploadInstructionRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int = Field(gt=0)


class UploadInstructionResponse(BaseModel):
    method: str
    bucket: str
    object_key: str
    upload_url: str
    headers: dict[str, str]
    expires_at: str
    max_size_bytes: int
    allowed_content_types: list[str]


class SensorReadingCreate(BaseModel):
    crop_cycle_id: str
    observed_at: datetime
    source_type: str = Field(min_length=1, max_length=30)
    metric_key: str = Field(min_length=1, max_length=80)
    metric_value: float
    unit: str | None = Field(default=None, max_length=30)
    metadata_json: dict = Field(default_factory=dict)


class SensorReadingResponse(BaseModel):
    id: str
    crop_cycle_id: str
    observed_at: datetime
    source_type: str
    metric_key: str
    metric_value: float
    unit: str | None
    metadata_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WaterFertilizerDecisionCreate(BaseModel):
    crop_cycle_id: str
    target_date: datetime
    check_items: list[str] = Field(default_factory=list)


class AIDecisionResponse(BaseModel):
    id: str
    crop_cycle_id: str
    decision_type: str
    risk_level: str
    summary: str
    recommendation_json: dict
    status: str
    created_by_user_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlantProtectionWorkOrderCreate(BaseModel):
    crop_cycle_id: str
    title: str = Field(min_length=1, max_length=300)
    risk_level: str
    due_at: datetime | None = None
    assigned_to_user_id: str | None = None
    recommendation: str = Field(min_length=1)
    follow_up_date: datetime | None = None
    check_items: list[str] = Field(default_factory=list)


class WorkOrderResponse(BaseModel):
    id: str
    crop_cycle_id: str
    decision_id: str | None
    domain: str
    title: str
    risk_level: str
    status: str
    assigned_to_user_id: str | None
    due_at: datetime | None
    requires_review: bool
    reviewer_id: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    guardrail_state: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkOrderReviewRequest(BaseModel):
    decision: str
    notes: str | None = None


class WorkOrderExecutionCreate(BaseModel):
    execution_mode: str = Field(min_length=1, max_length=30)
    executed_at: datetime
    evidence_refs: list[str] = Field(default_factory=list)
    result_notes: str | None = None
    anomaly_json: dict = Field(default_factory=dict)
    mark_completed: bool = False


class WorkOrderExecutionResponse(BaseModel):
    id: str
    work_order_id: str
    executor_user_id: str | None
    execution_mode: str
    executed_at: datetime
    evidence_refs: list[str]
    result_notes: str | None
    anomaly_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkOrderFeedbackCreate(BaseModel):
    metric_type: str = Field(min_length=1, max_length=80)
    metric_value: float
    unit: str | None = Field(default=None, max_length=30)
    notes: str | None = None
    metadata_json: dict = Field(default_factory=dict)
    recorded_at: datetime


class WorkOrderFeedbackResponse(BaseModel):
    id: str
    work_order_id: str
    decision_id: str | None
    metric_type: str
    metric_value: float
    unit: str | None
    notes: str | None
    metadata_json: dict
    recorded_by_user_id: str | None
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db()
        yield

    app = FastAPI(title="Strawberry AI Backend", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/auth/login", response_model=TokenResponse)
    def login(payload: LoginRequest, session: Session = session_dependency) -> TokenResponse:
        user = session.scalar(select(User).where(User.username == payload.username))
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        token = create_access_token(user_id=user.id, username=user.username, role=user.role)
        return TokenResponse(
            access_token=token,
            expires_in_seconds=get_settings().access_token_expires_minutes * 60,
        )

    @app.get("/api/v1/auth/me", response_model=UserResponse)
    def me(current_user: User = current_user_dependency) -> UserResponse:
        return UserResponse.model_validate(current_user)

    @app.post(
        "/api/v1/knowledge-documents",
        response_model=KnowledgeDocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_knowledge_document(
        payload: KnowledgeDocumentCreate,
        current_user: User = author_access_dependency,
        session: Session = session_dependency,
    ) -> KnowledgeDocumentResponse:
        _ensure_safe_knowledge_content(payload.title, payload.body)
        document = KnowledgeDocument(
            title=payload.title,
            body=payload.body,
            source=payload.source,
            region=payload.region,
            metadata_json=payload.metadata_json,
            author_id=current_user.id,
        )
        session.add(document)
        session.flush()
        _log_audit(
            session,
            entity_type="knowledge_document",
            entity_id=document.id,
            action="created",
            payload={"status": document.status, "author_id": current_user.id},
        )
        session.commit()
        session.refresh(document)
        return KnowledgeDocumentResponse.model_validate(document)

    @app.get("/api/v1/knowledge-documents", response_model=list[KnowledgeDocumentResponse])
    def list_knowledge_documents(
        status_filter: str | None = Query(default=None, alias="status"),
        current_user: User = current_user_dependency,
        session: Session = session_dependency,
    ) -> list[KnowledgeDocumentResponse]:
        query = select(KnowledgeDocument)
        if current_user.role == AUTHOR_ROLE:
            query = query.where(KnowledgeDocument.author_id == current_user.id)
        if status_filter:
            query = query.where(KnowledgeDocument.status == status_filter)
        documents = session.scalars(query.order_by(KnowledgeDocument.created_at.desc())).all()
        return [KnowledgeDocumentResponse.model_validate(document) for document in documents]

    @app.get("/api/v1/knowledge-documents/{document_id}", response_model=KnowledgeDocumentResponse)
    def get_knowledge_document(
        document_id: str,
        current_user: User = current_user_dependency,
        session: Session = session_dependency,
    ) -> KnowledgeDocumentResponse:
        document = _get_document_for_reader(session, document_id, current_user)
        return KnowledgeDocumentResponse.model_validate(document)

    @app.patch(
        "/api/v1/knowledge-documents/{document_id}", response_model=KnowledgeDocumentResponse
    )
    def update_knowledge_document(
        document_id: str,
        payload: KnowledgeDocumentUpdate,
        current_user: User = current_user_dependency,
        session: Session = session_dependency,
    ) -> KnowledgeDocumentResponse:
        document = _get_document_for_writer(session, document_id, current_user)
        if (
            document.status not in {DOCUMENT_DRAFT, DOCUMENT_REJECTED}
            and current_user.role != ADMIN_ROLE
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only draft or rejected documents can be edited.",
            )
        update_data = payload.model_dump(exclude_unset=True)
        merged_title = update_data.get("title", document.title)
        merged_body = update_data.get("body", document.body)
        _ensure_safe_knowledge_content(merged_title, merged_body)
        for field, value in update_data.items():
            setattr(document, field, value)
        document.updated_at = datetime.now(UTC)
        _log_audit(
            session,
            entity_type="knowledge_document",
            entity_id=document.id,
            action="updated",
            payload={"updated_fields": sorted(update_data.keys()), "actor_id": current_user.id},
        )
        session.commit()
        session.refresh(document)
        return KnowledgeDocumentResponse.model_validate(document)

    @app.post(
        "/api/v1/knowledge-documents/{document_id}/submit", response_model=KnowledgeDocumentResponse
    )
    def submit_knowledge_document(
        document_id: str,
        current_user: User = current_user_dependency,
        session: Session = session_dependency,
    ) -> KnowledgeDocumentResponse:
        document = _get_document_for_writer(session, document_id, current_user)
        if document.status not in {DOCUMENT_DRAFT, DOCUMENT_REJECTED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only draft or rejected documents can be submitted for review.",
            )
        now = datetime.now(UTC)
        document.status = DOCUMENT_SUBMITTED
        document.submitted_at = now
        document.reviewer_id = None
        document.review_notes = None
        document.reviewed_at = None
        document.approved_at = None
        document.rejected_at = None
        document.retired_at = None
        document.status_changed_at = now
        document.updated_at = now
        _log_audit(
            session,
            entity_type="knowledge_document",
            entity_id=document.id,
            action="submitted",
            payload={"actor_id": current_user.id},
        )
        session.commit()
        session.refresh(document)
        return KnowledgeDocumentResponse.model_validate(document)

    @app.post(
        "/api/v1/knowledge-documents/{document_id}/review", response_model=KnowledgeDocumentResponse
    )
    def review_knowledge_document(
        document_id: str,
        payload: KnowledgeReviewRequest,
        current_user: User = reviewer_access_dependency,
        session: Session = session_dependency,
    ) -> KnowledgeDocumentResponse:
        document = session.get(KnowledgeDocument, document_id)
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        if document.status != DOCUMENT_SUBMITTED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted documents can be reviewed.",
            )
        if payload.decision not in {DOCUMENT_APPROVED, DOCUMENT_REJECTED}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Review decision must be approved or rejected.",
            )
        now = datetime.now(UTC)
        document.status = payload.decision
        document.reviewer_id = current_user.id
        document.review_notes = payload.notes
        document.reviewed_at = now
        document.status_changed_at = now
        document.updated_at = now
        document.approved_at = now if payload.decision == DOCUMENT_APPROVED else None
        document.rejected_at = now if payload.decision == DOCUMENT_REJECTED else None
        _log_audit(
            session,
            entity_type="knowledge_document",
            entity_id=document.id,
            action=payload.decision,
            payload={"actor_id": current_user.id, "notes": payload.notes},
        )
        session.commit()
        session.refresh(document)
        return KnowledgeDocumentResponse.model_validate(document)

    @app.post(
        "/api/v1/knowledge-documents/{document_id}/retire", response_model=KnowledgeDocumentResponse
    )
    def retire_knowledge_document(
        document_id: str,
        current_user: User = admin_access_dependency,
        session: Session = session_dependency,
    ) -> KnowledgeDocumentResponse:
        document = session.get(KnowledgeDocument, document_id)
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        if document.status != DOCUMENT_APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only approved documents can be retired.",
            )
        now = datetime.now(UTC)
        document.status = DOCUMENT_RETIRED
        document.retired_at = now
        document.status_changed_at = now
        document.updated_at = now
        _log_audit(
            session,
            entity_type="knowledge_document",
            entity_id=document.id,
            action="retired",
            payload={"actor_id": current_user.id},
        )
        session.commit()
        session.refresh(document)
        return KnowledgeDocumentResponse.model_validate(document)

    @app.get("/api/v1/knowledge/search", response_model=KnowledgeSearchResponse)
    def search_knowledge(
        q: str = Query(default="", max_length=500),
        session: Session = session_dependency,
    ) -> KnowledgeSearchResponse:
        if _contains_restricted_knowledge(q):
            return KnowledgeSearchResponse(
                blocked=True,
                message="该请求涉及受限植保信息，系统不会提供剂量或混配建议，请联系农技员复核。",
                results=[],
            )
        query = select(KnowledgeDocument).where(KnowledgeDocument.status == DOCUMENT_APPROVED)
        cleaned = q.strip()
        if cleaned:
            like_value = f"%{cleaned}%"
            query = query.where(
                or_(
                    KnowledgeDocument.title.ilike(like_value),
                    KnowledgeDocument.body.ilike(like_value),
                    KnowledgeDocument.source.ilike(like_value),
                    KnowledgeDocument.region.ilike(like_value),
                )
            )
        documents = session.scalars(query.order_by(KnowledgeDocument.approved_at.desc())).all()
        results = [
            KnowledgeSearchResult(
                id=document.id,
                title=document.title,
                source=document.source,
                region=document.region,
                excerpt=document.body[:160],
            )
            for document in documents
        ]
        return KnowledgeSearchResponse(results=results)

    @app.post(
        "/api/v1/uploads/image-instructions",
        response_model=UploadInstructionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_upload_instruction(
        payload: UploadInstructionRequest,
        current_user: User = current_user_dependency,
        session: Session = session_dependency,
    ) -> UploadInstructionResponse:
        instruction = build_signed_upload_instruction(
            owner_id=current_user.id,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
        )
        _log_audit(
            session,
            entity_type="upload_instruction",
            entity_id=current_user.id,
            action="created",
            payload={
                "content_type": payload.content_type,
                "size_bytes": payload.size_bytes,
                "object_key": instruction["object_key"],
            },
        )
        session.commit()
        return UploadInstructionResponse.model_validate(instruction)

    @app.post(
        "/api/v1/sensor-readings",
        response_model=SensorReadingResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_sensor_reading(
        payload: SensorReadingCreate,
        current_user: User = author_access_dependency,
        session: Session = session_dependency,
    ) -> SensorReadingResponse:
        _ensure_crop_cycle_exists(session, payload.crop_cycle_id)
        reading = SensorReading(
            crop_cycle_id=payload.crop_cycle_id,
            observed_at=payload.observed_at,
            source_type=payload.source_type,
            metric_key=payload.metric_key,
            metric_value=payload.metric_value,
            unit=payload.unit,
            metadata_json=payload.metadata_json,
        )
        session.add(reading)
        session.flush()
        _emit_domain_event(
            session,
            entity_type="sensor_reading",
            entity_id=reading.id,
            event_type="sensed.sensor_reading_recorded",
            payload={
                "crop_cycle_id": reading.crop_cycle_id,
                "metric_key": reading.metric_key,
                "source_type": reading.source_type,
                "actor_id": current_user.id,
            },
        )
        session.commit()
        session.refresh(reading)
        return SensorReadingResponse.model_validate(reading)

    @app.post(
        "/api/v1/decisions/water-fertilizer",
        response_model=AIDecisionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_water_fertilizer_decision(
        payload: WaterFertilizerDecisionCreate,
        current_user: User = author_access_dependency,
        session: Session = session_dependency,
    ) -> AIDecisionResponse:
        _ensure_crop_cycle_exists(session, payload.crop_cycle_id)
        recommendation, risk_level = _build_water_fertilizer_recommendation(
            session, payload.crop_cycle_id, payload.check_items
        )
        decision = AIDecision(
            crop_cycle_id=payload.crop_cycle_id,
            decision_type="water_fertilizer",
            risk_level=risk_level,
            summary=recommendation["summary"],
            recommendation_json={
                "target_date": payload.target_date.isoformat(),
                "irrigation_plan": recommendation["irrigation_plan"],
                "fertilizer_plan": recommendation["fertilizer_plan"],
                "risk_tips": recommendation["risk_tips"],
                "check_items": recommendation["check_items"],
            },
            status="proposed",
            created_by_user_id=current_user.id,
        )
        session.add(decision)
        session.flush()
        _emit_domain_event(
            session,
            entity_type="ai_decision",
            entity_id=decision.id,
            event_type="analyzed.water_fertilizer_decision_proposed",
            payload={
                "crop_cycle_id": decision.crop_cycle_id,
                "risk_level": decision.risk_level,
                "actor_id": current_user.id,
            },
        )
        session.commit()
        session.refresh(decision)
        return AIDecisionResponse.model_validate(decision)

    @app.post(
        "/api/v1/work-orders/plant-protection",
        response_model=WorkOrderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_plant_protection_work_order(
        payload: PlantProtectionWorkOrderCreate,
        current_user: User = author_access_dependency,
        session: Session = session_dependency,
    ) -> WorkOrderResponse:
        _ensure_crop_cycle_exists(session, payload.crop_cycle_id)
        _validate_risk_level(payload.risk_level)
        recommendation_text = payload.recommendation.strip()
        if _contains_restricted_knowledge(recommendation_text):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Plant-protection recommendation cannot include dosage or mixing details.",
            )
        requires_review = payload.risk_level in {RISK_HIGH, RISK_BLOCKED}
        work_order = WorkOrder(
            crop_cycle_id=payload.crop_cycle_id,
            domain="plant_protection",
            title=payload.title,
            risk_level=payload.risk_level,
            status=WORK_ORDER_PENDING_REVIEW if requires_review else WORK_ORDER_OPEN,
            assigned_to_user_id=payload.assigned_to_user_id,
            due_at=payload.due_at,
            requires_review=requires_review,
            guardrail_state="escalated" if requires_review else "normal",
        )
        session.add(work_order)
        session.flush()
        decision = AIDecision(
            crop_cycle_id=payload.crop_cycle_id,
            decision_type="plant_protection",
            risk_level=payload.risk_level,
            summary=payload.title,
            recommendation_json={
                "recommendation": recommendation_text,
                "check_items": payload.check_items,
                "follow_up_date": payload.follow_up_date.isoformat()
                if payload.follow_up_date
                else None,
            },
            status="review_required" if requires_review else "proposed",
            created_by_user_id=current_user.id,
        )
        session.add(decision)
        session.flush()
        work_order.decision_id = decision.id
        _emit_domain_event(
            session,
            entity_type="work_order",
            entity_id=work_order.id,
            event_type="decided.plant_protection_work_order_created",
            payload={
                "risk_level": work_order.risk_level,
                "requires_review": work_order.requires_review,
                "actor_id": current_user.id,
            },
        )
        session.commit()
        session.refresh(work_order)
        return WorkOrderResponse.model_validate(work_order)

    @app.post("/api/v1/work-orders/{work_order_id}/review", response_model=WorkOrderResponse)
    def review_work_order(
        work_order_id: str,
        payload: WorkOrderReviewRequest,
        current_user: User = reviewer_access_dependency,
        session: Session = session_dependency,
    ) -> WorkOrderResponse:
        work_order = _get_work_order(session, work_order_id)
        if not work_order.requires_review:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This work order does not require reviewer approval.",
            )
        if work_order.status != WORK_ORDER_PENDING_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only pending-review work orders can be reviewed.",
            )
        if payload.decision not in {"approved", "rejected"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Review decision must be approved or rejected.",
            )
        now = datetime.now(UTC)
        work_order.reviewer_id = current_user.id
        work_order.reviewed_at = now
        work_order.review_notes = payload.notes
        work_order.updated_at = now
        if payload.decision == "approved":
            work_order.status = WORK_ORDER_OPEN
            work_order.guardrail_state = "normal"
        else:
            work_order.status = WORK_ORDER_REJECTED
            work_order.guardrail_state = "blocked"
        _emit_domain_event(
            session,
            entity_type="work_order",
            entity_id=work_order.id,
            event_type=f"decided.work_order_{payload.decision}",
            payload={"actor_id": current_user.id, "notes": payload.notes},
        )
        session.commit()
        session.refresh(work_order)
        return WorkOrderResponse.model_validate(work_order)

    @app.post(
        "/api/v1/work-orders/{work_order_id}/executions",
        response_model=WorkOrderExecutionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_work_order_execution(
        work_order_id: str,
        payload: WorkOrderExecutionCreate,
        current_user: User = author_access_dependency,
        session: Session = session_dependency,
    ) -> WorkOrderExecutionResponse:
        work_order = _get_work_order(session, work_order_id)
        if work_order.status == WORK_ORDER_PENDING_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Work order is pending reviewer approval.",
            )
        if work_order.status in {WORK_ORDER_CANCELLED, WORK_ORDER_REJECTED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot execute a cancelled or rejected work order.",
            )
        execution = WorkOrderExecution(
            work_order_id=work_order.id,
            executor_user_id=current_user.id,
            execution_mode=payload.execution_mode,
            executed_at=payload.executed_at,
            evidence_refs=payload.evidence_refs,
            result_notes=payload.result_notes,
            anomaly_json=payload.anomaly_json,
        )
        session.add(execution)
        work_order.status = WORK_ORDER_COMPLETED if payload.mark_completed else WORK_ORDER_IN_PROGRESS
        work_order.updated_at = datetime.now(UTC)
        session.flush()
        _emit_domain_event(
            session,
            entity_type="work_order_execution",
            entity_id=execution.id,
            event_type="executed.work_order_execution_recorded",
            payload={
                "work_order_id": work_order.id,
                "status": work_order.status,
                "actor_id": current_user.id,
            },
        )
        session.commit()
        session.refresh(execution)
        return WorkOrderExecutionResponse.model_validate(execution)

    @app.post(
        "/api/v1/work-orders/{work_order_id}/feedback",
        response_model=WorkOrderFeedbackResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_work_order_feedback(
        work_order_id: str,
        payload: WorkOrderFeedbackCreate,
        current_user: User = author_access_dependency,
        session: Session = session_dependency,
    ) -> WorkOrderFeedbackResponse:
        work_order = _get_work_order(session, work_order_id)
        feedback = WorkOrderFeedback(
            work_order_id=work_order.id,
            decision_id=work_order.decision_id,
            metric_type=payload.metric_type,
            metric_value=payload.metric_value,
            unit=payload.unit,
            notes=payload.notes,
            metadata_json=payload.metadata_json,
            recorded_by_user_id=current_user.id,
            recorded_at=payload.recorded_at,
        )
        session.add(feedback)
        session.flush()
        _emit_domain_event(
            session,
            entity_type="work_order_feedback",
            entity_id=feedback.id,
            event_type="feedback.work_order_feedback_recorded",
            payload={
                "work_order_id": work_order.id,
                "metric_type": feedback.metric_type,
                "actor_id": current_user.id,
            },
        )
        session.commit()
        session.refresh(feedback)
        return WorkOrderFeedbackResponse.model_validate(feedback)

    return app


def _contains_restricted_knowledge(value: str) -> bool:
    return any(term in value for term in RESTRICTED_KNOWLEDGE_TERMS)


def _validate_risk_level(risk_level: str) -> None:
    if risk_level not in {RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_BLOCKED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported risk level.",
        )


def _ensure_crop_cycle_exists(session: Session, crop_cycle_id: str) -> None:
    if session.get(CropCycle, crop_cycle_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop cycle not found.")


def _get_work_order(session: Session, work_order_id: str) -> WorkOrder:
    work_order = session.get(WorkOrder, work_order_id)
    if work_order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found.")
    return work_order


def _build_water_fertilizer_recommendation(
    session: Session, crop_cycle_id: str, check_items: list[str]
) -> tuple[dict[str, Any], str]:
    readings = session.scalars(
        select(SensorReading)
        .where(SensorReading.crop_cycle_id == crop_cycle_id)
        .order_by(SensorReading.observed_at.desc())
        .limit(100)
    ).all()
    latest_by_metric: dict[str, SensorReading] = {}
    for reading in readings:
        latest_by_metric.setdefault(reading.metric_key, reading)
    moisture = latest_by_metric.get("substrate_moisture") or latest_by_metric.get("soil_moisture")
    ec = latest_by_metric.get("ec")
    moisture_value = moisture.metric_value if moisture else None
    ec_value = ec.metric_value if ec else None
    risk_level = RISK_MEDIUM if moisture_value is None else RISK_LOW
    irrigation_plan = "建议补充观测后再灌溉。"
    if moisture_value is not None and moisture_value < 28:
        irrigation_plan = "建议执行小水勤灌，优先早晚时段分次灌溉。"
    elif moisture_value is not None and moisture_value > 55:
        irrigation_plan = "建议暂停灌溉并检查排水，防止根腐风险。"
        risk_level = RISK_HIGH
    fertilizer_plan = "保持当前施肥策略，结合最近生育期台账复核。"
    if ec_value is not None and ec_value < 1.0:
        fertilizer_plan = "EC 偏低，建议小幅补充水溶肥并复测。"
    elif ec_value is not None and ec_value > 2.5:
        fertilizer_plan = "EC 偏高，建议先清水缓冲并复测后再追肥。"
        risk_level = RISK_HIGH if risk_level != RISK_HIGH else risk_level
    risk_tips = []
    if moisture_value is None:
        risk_tips.append("缺少基质含水率，建议先补齐传感器或人工观测。")
    if ec_value is None:
        risk_tips.append("缺少 EC 数据，施肥建议可信度受限。")
    if not risk_tips:
        risk_tips.append("执行前确认阀门状态、流量计和棚室温湿度。")
    merged_check_items = check_items or [
        "确认灌溉阀门和泵站状态",
        "确认目标棚室与作业时段",
        "执行后 30 分钟回传传感器数据",
    ]
    return (
        {
            "summary": "水肥建议已生成，可转工单执行并进行回传评估。",
            "irrigation_plan": irrigation_plan,
            "fertilizer_plan": fertilizer_plan,
            "risk_tips": risk_tips,
            "check_items": merged_check_items,
        },
        risk_level,
    )


def _ensure_safe_knowledge_content(title: str, body: str) -> None:
    combined = f"{title}\n{body}"
    if _contains_restricted_knowledge(combined):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge documents must not store pesticide dosage or mixing instructions.",
        )


def _get_document_for_reader(
    session: Session, document_id: str, current_user: User
) -> KnowledgeDocument:
    document = session.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if current_user.role == AUTHOR_ROLE and document.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to read this document.",
        )
    return document


def _get_document_for_writer(
    session: Session, document_id: str, current_user: User
) -> KnowledgeDocument:
    document = session.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if current_user.role == ADMIN_ROLE:
        return document
    if document.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this document.",
        )
    return document


def _log_audit(
    session: Session, *, entity_type: str, entity_id: str, action: str, payload: dict
) -> None:
    session.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            payload=json.loads(json.dumps(payload, default=str)),
        )
    )


def _emit_domain_event(
    session: Session, *, entity_type: str, entity_id: str, event_type: str, payload: dict
) -> None:
    session.add(
        DomainEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload=json.loads(json.dumps(payload, default=str)),
        )
    )
    _log_audit(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        action=event_type,
        payload=payload,
    )


app = create_app()
