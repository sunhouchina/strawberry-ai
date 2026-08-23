from functools import lru_cache
import os


@lru_cache
def database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./strawberry_ai.db")
