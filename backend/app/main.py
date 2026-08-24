import hashlib
import hmac
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import (
    access_token_expire_seconds,
    allowed_upload_content_types,
    object_storage_access_key,
    object_storage_bucket,
    object_storage_configured,
    object_storage_endpoint,
    object_storage_secret_key,
    signed_upload_expire_seconds,
    upload_max_size_bytes,
)
from app.db import get_engine, get_session
from app.models import AuditLog, KnowledgeDocument, User
from app.security import (
    authenticate_user,
    create_access_token,
    get_current_user,
    require_roles,
)

BLOCKED_TERMS = (
    "剂量",
    "用量",
    "稀释",
    "配比",
    "混配",
    "间隔期",
    "采收安全期",
    "pesticide dosage",
    "tank mix",
    "dilution ratio",
    "pre-harvest interval",
)
BLOCKED_RATIO_PATTERN = re.compile(r"\b\d+\s*[:：/]\s*\d+\b")
UPLOAD_EXTENSION_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
KNOWLEDGE_STATUS_DRAFT = "draft"
KNOWLEDGE_STATUS_PENDING = "pending_review"
KNOWLEDGE_STATUS_APPROVED = "approved"
KNOWLEDGE_STATUS_REJECTED = "rejected"
KNOWLEDGE_STATUS_RETIRED = "retired"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from app.db import Base

    Base.metadata.create_all(bind=get_engine())
    yield


app = FastAPI(title="Strawberry AI Backend", lifespan=lifespan)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: str


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source: str = Field(min_length=1, max_length=300)
    region: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1)
    metadata_json: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class KnowledgeDocumentReview(BaseModel):
    action: str
    review_notes: str | None = None


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source: str
    region: str | None
    content: str
    status: str
    author_id: str
    submitted_by_id: str | None
    reviewed_by_id: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    approved_at: datetime | None
    rejected_at: datetime | None
    retired_at: datetime | None
    review_notes: str | None
    status_changed_at: datetime
    metadata_json: dict[str, str | int | float | bool | None]


class UploadInstructionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0)


class SignedUploadResponse(BaseModel):
    upload_url: str
    method: str
    object_key: str
    expires_at: datetime
    max_size_bytes: int
    fields: dict[str, str | int]


def contains_blocked_content(*values: str | None) -> bool:
    combined = " ".join(value for value in values if value)
    lowered = combined.casefold()
    return any(term in lowered for term in BLOCKED_TERMS) or bool(
        BLOCKED_RATIO_PATTERN.search(combined)
    )


def audit(
    session: Session,
    *,
    actor_id: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    payload: dict[str, str | int | float | bool | None],
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            payload=payload,
        )
    )


def require_document_visibility(
    session: Session, document_id: str, user: User
) -> KnowledgeDocument:
    document = session.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found."
        )
    if user.role in {"reviewer", "admin"} or document.author_id == user.id:
        return document
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this knowledge document.",
    )


def ensure_transition(document: KnowledgeDocument, target_status: str) -> None:
    allowed = {
        KNOWLEDGE_STATUS_DRAFT: {KNOWLEDGE_STATUS_PENDING},
        KNOWLEDGE_STATUS_REJECTED: {KNOWLEDGE_STATUS_PENDING},
        KNOWLEDGE_STATUS_PENDING: {KNOWLEDGE_STATUS_APPROVED, KNOWLEDGE_STATUS_REJECTED},
        KNOWLEDGE_STATUS_APPROVED: {KNOWLEDGE_STATUS_RETIRED},
        KNOWLEDGE_STATUS_RETIRED: set(),
    }
    current_allowed = allowed.get(document.status, set())
    if target_status not in current_allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid knowledge document transition from {document.status} to {target_status}.",
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/token", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    user = authenticate_user(session, payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    token = create_access_token(user)
    return TokenResponse(
        access_token=token,
        expires_in=access_token_expire_seconds(),
        role=user.role,
    )


@app.get("/api/v1/auth/me", response_model=UserResponse)
def read_current_user(user: User = Depends(get_current_user)) -> User:
    return user


@app.post(
    "/api/v1/knowledge-documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_document(
    payload: KnowledgeDocumentCreate,
    user: User = Depends(require_roles("author", "reviewer", "admin")),
    session: Session = Depends(get_session),
) -> KnowledgeDocument:
    if contains_blocked_content(payload.title, payload.content):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Knowledge documents must not store dosage, tank-mixing, dilution, or harvest interval instructions.",
        )
    document = KnowledgeDocument(
        title=payload.title,
        source=payload.source,
        region=payload.region,
        content=payload.content,
        author_id=user.id,
        metadata_json=dict(payload.metadata_json),
        status=KNOWLEDGE_STATUS_DRAFT,
        status_changed_at=datetime.now(UTC),
    )
    session.add(document)
    session.flush()
    audit(
        session,
        actor_id=user.id,
        entity_type="knowledge_document",
        entity_id=document.id,
        action="created",
        payload={"status": document.status},
    )
    session.commit()
    session.refresh(document)
    return document


@app.get("/api/v1/knowledge-documents", response_model=list[KnowledgeDocumentResponse])
def list_knowledge_documents(
    user: User = Depends(require_roles("author", "reviewer", "admin")),
    session: Session = Depends(get_session),
) -> list[KnowledgeDocument]:
    query = session.query(KnowledgeDocument)
    if user.role == "author":
        query = query.filter(KnowledgeDocument.author_id == user.id)
    return query.order_by(KnowledgeDocument.status_changed_at.desc()).all()


@app.get("/api/v1/knowledge/public", response_model=list[KnowledgeDocumentResponse])
@app.get("/api/v1/knowledge-documents/public", response_model=list[KnowledgeDocumentResponse])
def list_public_knowledge_documents(
    query: str | None = Query(default=None, max_length=200),
    session: Session = Depends(get_session),
) -> list[KnowledgeDocument]:
    if contains_blocked_content(query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dosage, tank-mixing, dilution, and harvest interval requests are blocked.",
        )
    documents_query = session.query(KnowledgeDocument).filter(
        KnowledgeDocument.status == KNOWLEDGE_STATUS_APPROVED
    )
    if query:
        like_value = f"%{query}%"
        documents_query = documents_query.filter(
            (KnowledgeDocument.title.like(like_value))
            | (KnowledgeDocument.content.like(like_value))
        )
    return documents_query.order_by(KnowledgeDocument.status_changed_at.desc()).all()


@app.get("/api/v1/knowledge-documents/{document_id}", response_model=KnowledgeDocumentResponse)
def get_knowledge_document(
    document_id: str,
    user: User = Depends(require_roles("author", "reviewer", "admin")),
    session: Session = Depends(get_session),
) -> KnowledgeDocument:
    return require_document_visibility(session, document_id, user)


@app.post(
    "/api/v1/knowledge-documents/{document_id}/submit", response_model=KnowledgeDocumentResponse
)
def submit_knowledge_document(
    document_id: str,
    user: User = Depends(require_roles("author", "admin")),
    session: Session = Depends(get_session),
) -> KnowledgeDocument:
    document = require_document_visibility(session, document_id, user)
    if user.role != "admin" and document.author_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author may submit this knowledge document.",
        )
    ensure_transition(document, KNOWLEDGE_STATUS_PENDING)
    submitted_at = datetime.now(UTC)
    document.status = KNOWLEDGE_STATUS_PENDING
    document.submitted_by_id = user.id
    document.submitted_at = submitted_at
    document.status_changed_at = submitted_at
    audit(
        session,
        actor_id=user.id,
        entity_type="knowledge_document",
        entity_id=document.id,
        action="submitted",
        payload={"status": document.status},
    )
    session.commit()
    session.refresh(document)
    return document


@app.post(
    "/api/v1/knowledge-documents/{document_id}/review", response_model=KnowledgeDocumentResponse
)
def review_knowledge_document(
    document_id: str,
    payload: KnowledgeDocumentReview,
    user: User = Depends(require_roles("reviewer", "admin")),
    session: Session = Depends(get_session),
) -> KnowledgeDocument:
    document = require_document_visibility(session, document_id, user)
    if user.role != "admin" and document.author_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewers cannot review their own knowledge documents.",
        )
    action = payload.action.casefold()
    if action == "approve":
        target_status = KNOWLEDGE_STATUS_APPROVED
    elif action == "reject":
        target_status = KNOWLEDGE_STATUS_REJECTED
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Review action must be approve or reject.",
        )
    ensure_transition(document, target_status)
    reviewed_at = datetime.now(UTC)
    document.status = target_status
    document.reviewed_by_id = user.id
    document.reviewed_at = reviewed_at
    document.review_notes = payload.review_notes
    document.status_changed_at = reviewed_at
    document.approved_at = reviewed_at if target_status == KNOWLEDGE_STATUS_APPROVED else None
    document.rejected_at = reviewed_at if target_status == KNOWLEDGE_STATUS_REJECTED else None
    audit(
        session,
        actor_id=user.id,
        entity_type="knowledge_document",
        entity_id=document.id,
        action=target_status,
        payload={"status": document.status, "review_notes": payload.review_notes},
    )
    session.commit()
    session.refresh(document)
    return document


@app.post(
    "/api/v1/knowledge-documents/{document_id}/retire", response_model=KnowledgeDocumentResponse
)
def retire_knowledge_document(
    document_id: str,
    user: User = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> KnowledgeDocument:
    document = require_document_visibility(session, document_id, user)
    ensure_transition(document, KNOWLEDGE_STATUS_RETIRED)
    retired_at = datetime.now(UTC)
    document.status = KNOWLEDGE_STATUS_RETIRED
    document.retired_at = retired_at
    document.status_changed_at = retired_at
    audit(
        session,
        actor_id=user.id,
        entity_type="knowledge_document",
        entity_id=document.id,
        action="retired",
        payload={"status": document.status},
    )
    session.commit()
    session.refresh(document)
    return document


@app.post("/api/v1/uploads/image-instructions", response_model=SignedUploadResponse)
def create_image_upload_instructions(
    payload: UploadInstructionRequest,
    user: User = Depends(get_current_user),
) -> SignedUploadResponse:
    if not object_storage_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is not configured.",
        )
    if payload.content_type not in allowed_upload_content_types():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported image content type.",
        )
    max_size = upload_max_size_bytes()
    if payload.size_bytes > max_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Image exceeds the configured upload size limit.",
        )
    expires_at = datetime.now(UTC) + timedelta(seconds=signed_upload_expire_seconds())
    extension = UPLOAD_EXTENSION_BY_TYPE[payload.content_type]
    object_key = f"uploads/{user.id}/{uuid4().hex}.{extension}"
    policy = {
        "bucket": object_storage_bucket(),
        "key": object_key,
        "content_type": payload.content_type,
        "max_size_bytes": max_size,
        "owner_id": user.id,
        "expires_at": expires_at.isoformat(),
    }
    policy_json = json.dumps(policy, separators=(",", ":"), sort_keys=True)
    signature = hmac.new(
        object_storage_secret_key().encode("utf-8"),
        policy_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return SignedUploadResponse(
        upload_url=f"{object_storage_endpoint().rstrip('/')}/{object_storage_bucket()}",
        method="POST",
        object_key=object_key,
        expires_at=expires_at,
        max_size_bytes=max_size,
        fields={
            "policy": policy_json,
            "signature": signature,
            "access_key": object_storage_access_key() or "",
            "key": object_key,
            "content_type": payload.content_type,
            "expires_at": policy["expires_at"],
            "max_size_bytes": max_size,
        },
    )
