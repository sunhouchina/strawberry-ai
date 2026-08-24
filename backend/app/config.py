import os
from functools import lru_cache


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


@lru_cache
def database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./strawberry_ai.db")


@lru_cache
def jwt_secret_key() -> str:
    return os.getenv("JWT_SECRET_KEY", "local-dev-jwt-secret-change-me")


@lru_cache
def access_token_expire_seconds() -> int:
    return _int_env("ACCESS_TOKEN_EXPIRE_SECONDS", 3600)


@lru_cache
def object_storage_endpoint() -> str | None:
    return os.getenv("OBJECT_STORAGE_ENDPOINT")


@lru_cache
def object_storage_bucket() -> str | None:
    return os.getenv("OBJECT_STORAGE_BUCKET")


@lru_cache
def object_storage_access_key() -> str | None:
    return os.getenv("OBJECT_STORAGE_ACCESS_KEY")


@lru_cache
def object_storage_secret_key() -> str | None:
    return os.getenv("OBJECT_STORAGE_SECRET_KEY")


@lru_cache
def signed_upload_expire_seconds() -> int:
    return _int_env("SIGNED_UPLOAD_EXPIRE_SECONDS", 300)


@lru_cache
def upload_max_size_bytes() -> int:
    return _int_env("UPLOAD_MAX_SIZE_BYTES", 5 * 1024 * 1024)


@lru_cache
def allowed_upload_content_types() -> tuple[str, ...]:
    configured = os.getenv("ALLOWED_UPLOAD_CONTENT_TYPES")
    if configured:
        return tuple(item.strip() for item in configured.split(",") if item.strip())
    return ("image/jpeg", "image/png", "image/webp")


def object_storage_configured() -> bool:
    return all(
        (
            object_storage_endpoint(),
            object_storage_bucket(),
            object_storage_access_key(),
            object_storage_secret_key(),
        )
    )
