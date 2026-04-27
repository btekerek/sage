"""FastAPI dependencies for authentication and authorisation."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.security import decode_token
from app.infrastructure.models.user import UserModel

bearer_scheme = HTTPBearer()


class CurrentUser(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: AsyncSession = Depends(get_db_session),
) -> CurrentUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_error
    except JWTError:
        raise credentials_error

    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_error

    return CurrentUser(id=user.id, email=user.email, role=user.role, is_active=user.is_active)


def require_roles(*roles: str):
    """Dependency factory: raises 403 if the current user's role is not in the allowed set."""

    async def _check(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not permitted for this action.",
            )
        return current_user

    return _check


# Convenience aliases
require_admin = require_roles("admin")
require_manager_or_above = require_roles("admin", "manager")
require_any_staff = require_roles("admin", "manager", "staff")
