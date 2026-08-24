from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from app.config import get_settings

CONTENT_TYPE_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def build_signed_upload_instruction(*, owner_id: str, content_type: str, size_bytes: int) -> dict:
    settings = get_settings()
    if not (
        settings.storage_bucket
        and settings.storage_endpoint_base
        and settings.storage_signing_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage upload is not configured.",
        )
    if content_type not in settings.allowed_upload_content_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported content type for image upload.",
        )
    if size_bytes < 1 or size_bytes > settings.storage_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image size exceeds the configured upload limit.",
        )
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.storage_upload_ttl_seconds)
    object_key = (
        f"uploads/{owner_id}/{expires_at.strftime('%Y%m%d')}/"
        f"{uuid.uuid4().hex}{CONTENT_TYPE_TO_EXTENSION[content_type]}"
    )
    signature_payload = (
        f"PUT\n{settings.storage_bucket}\n{object_key}\n{content_type}\n"
        f"{size_bytes}\n{int(expires_at.timestamp())}"
    )
    signature = hmac.new(
        settings.storage_signing_secret.encode("utf-8"),
        signature_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    base_url = settings.storage_endpoint_base.rstrip("/")
    return {
        "method": "PUT",
        "bucket": settings.storage_bucket,
        "object_key": object_key,
        "upload_url": (
            f"{base_url}/{settings.storage_bucket}/{object_key}"
            f"?expires={int(expires_at.timestamp())}&signature={signature}"
        ),
        "headers": {
            "Content-Type": content_type,
            "Content-Length": str(size_bytes),
            "x-strawberry-upload-owner": owner_id,
        },
        "expires_at": expires_at.isoformat(),
        "max_size_bytes": settings.storage_max_upload_bytes,
        "allowed_content_types": list(settings.allowed_upload_content_types),
    }
