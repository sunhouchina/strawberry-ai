from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_options(database_url: str) -> dict:
    options: dict = {"future": True}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            options["poolclass"] = StaticPool
    return options


@lru_cache
def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url, **_engine_options(settings.database_url))


@lru_cache
def get_session_factory():
    return sessionmaker(
        bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False
    )


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


def reset_db_cache() -> None:
    get_session_factory.cache_clear()
    engine = None
    if hasattr(get_engine, "cache_info"):
        cached = get_engine.cache_info().currsize
        if cached:
            engine = get_engine()
    get_engine.cache_clear()
    if engine is not None:
        engine.dispose()


def get_session():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
