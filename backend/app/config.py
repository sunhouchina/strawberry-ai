import os
import secrets
from dataclasses import dataclass
from functools import lru_cache


def _split_csv(raw_value: str, default: tuple[str, ...]) -> tuple[str, ...]:
    values = tuple(item.strip() for item in raw_value.split(",") if item.strip())
    return values or default


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret_key: str
    access_token_expires_minutes: int
    storage_bucket: str | None
    storage_endpoint_base: str | None
    storage_signing_secret: str | None
    storage_upload_ttl_seconds: int
    storage_max_upload_bytes: int
    allowed_upload_content_types: tuple[str, ...]


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./strawberry_ai.db"),
        jwt_secret_key=os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(32),
        access_token_expires_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRES_MINUTES", "30")),
        storage_bucket=os.getenv("STORAGE_BUCKET"),
        storage_endpoint_base=os.getenv("STORAGE_ENDPOINT_BASE"),
        storage_signing_secret=os.getenv("STORAGE_SIGNING_SECRET"),
        storage_upload_ttl_seconds=int(os.getenv("STORAGE_UPLOAD_TTL_SECONDS", "300")),
        storage_max_upload_bytes=int(os.getenv("STORAGE_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
        allowed_upload_content_types=_split_csv(
            os.getenv("ALLOWED_UPLOAD_CONTENT_TYPES", "image/jpeg,image/png,image/webp"),
            ("image/jpeg", "image/png", "image/webp"),
        ),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
