from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import create_access_token, verify_password
from app.config import get_settings
from app.db import get_session, init_db
from app.models import AuditLog, KnowledgeDocument, User
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

    return app


def _contains_restricted_knowledge(value: str) -> bool:
    return any(term in value for term in RESTRICTED_KNOWLEDGE_TERMS)


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


app = create_app()
