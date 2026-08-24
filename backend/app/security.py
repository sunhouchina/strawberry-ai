import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import access_token_expire_seconds, jwt_secret_key
from app.db import get_session
from app.models import User

ALGORITHM = "HS256"
PASSWORD_HASH_PREFIX = "scrypt"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64

bearer_scheme = HTTPBearer(auto_error=False)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return (
        f"{PASSWORD_HASH_PREFIX}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
        f"{_b64url_encode(salt)}${_b64url_encode(derived)}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        prefix, n_value, r_value, p_value, salt_value, hash_value = password_hash.split("$")
    except ValueError:
        return False
    if prefix != PASSWORD_HASH_PREFIX:
        return False
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=_b64url_decode(salt_value),
        n=int(n_value),
        r=int(r_value),
        p=int(p_value),
        dklen=SCRYPT_DKLEN,
    )
    return hmac.compare_digest(_b64url_encode(derived), hash_value)


def create_access_token(user: User) -> str:
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=access_token_expire_seconds())
    payload = {
        "sub": user.id,
        "role": user.role,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    header = {"alg": ALGORITHM, "typ": "JWT"}
    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    message = f"{header_segment}.{payload_segment}".encode()
    signature = hmac.new(jwt_secret_key().encode("utf-8"), message, hashlib.sha256).digest()
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, int | str]:
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        ) from error
    message = f"{header_segment}.{payload_segment}".encode()
    expected_signature = _b64url_encode(
        hmac.new(jwt_secret_key().encode("utf-8"), message, hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected_signature, signature_segment):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )
    payload = json.loads(_b64url_decode(payload_segment))
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at < int(datetime.now(UTC).timestamp()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token expired.",
        )
    return payload


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    user = session.query(User).filter(User.username == username).first()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )
    payload = decode_access_token(credentials.credentials)
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )
    user = session.query(User).filter(User.id == subject).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user is unavailable.",
        )
    return user


def require_roles(*allowed_roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return dependency
