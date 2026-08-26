from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from app.config import get_settings

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    role: str
    username: str
    expires_at: datetime


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(f"{raw}{padding}")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return (
        f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(derived_key).decode('ascii')}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_b64, key_b64 = password_hash.split("$", 5)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=base64.b64decode(salt_b64),
        n=int(n_value),
        r=int(r_value),
        p=int(p_value),
        dklen=len(base64.b64decode(key_b64)),
    )
    return hmac.compare_digest(derived_key, base64.b64decode(key_b64))


def create_access_token(
    *, user_id: str, username: str, role: str, expires_in_minutes: int | None = None
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(
        minutes=expires_in_minutes
        if expires_in_minutes is not None
        else settings.access_token_expires_minutes
    )
    header_segment = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    payload_segment = _b64url_encode(
        json.dumps(
            {
                "sub": user_id,
                "usr": username,
                "role": role,
                "iat": int(now.timestamp()),
                "exp": int(expires_at.timestamp()),
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode()
    signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> TokenPayload:
    try:
        header_segment, payload_segment, signature_segment = token.split(".", 2)
    except ValueError as exc:
        raise _invalid_token_error() from exc
    signing_input = f"{header_segment}.{payload_segment}".encode()
    expected_signature = hmac.new(
        get_settings().jwt_secret_key.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected_signature, _b64url_decode(signature_segment)):
        raise _invalid_token_error()
    try:
        payload = json.loads(_b64url_decode(payload_segment))
        expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid_token_error() from exc
    if expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenPayload(
        user_id=payload["sub"],
        role=payload["role"],
        username=payload["usr"],
        expires_at=expires_at,
    )


def _invalid_token_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid access token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
