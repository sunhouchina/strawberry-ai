from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import decode_access_token
from app.db import get_session
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)
credentials_dependency = Depends(bearer_scheme)
session_dependency = Depends(get_session)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = credentials_dependency,
    session: Session = session_dependency,
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    user = session.scalar(select(User).where(User.id == payload.user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user is unavailable.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


current_user_dependency = Depends(get_current_user)


def require_roles(*roles: str) -> Callable:
    def dependency(current_user: User = current_user_dependency) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return dependency
