"""User management routes (admin only).

GET    /api/users           — list all users
POST   /api/users           — create a user
PATCH  /api/users/{id}      — update role / active status
DELETE /api/users/{id}      — delete a user

POST   /api/users/seed-admin  — creates the first admin if no users exist (bootstrap only)
"""

import re
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_admin, require_manager_or_above
from app.core.db import get_db_session
from app.core.security import hash_password
from app.infrastructure.models.user import UserModel

router = APIRouter(prefix="/api/users", tags=["users"])

ALLOWED_ROLES = {"admin", "manager", "staff"}

PASSWORD_POLICY = (
    "Password must be at least 8 characters and contain an uppercase letter, "
    "a number, and a special character."
)


def _validate_password(v: str) -> str:
    if (
        len(v) < 8
        or not re.search(r"[A-Z]", v)
        or not re.search(r"[0-9]", v)
        or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v)
    ):
        raise ValueError(PASSWORD_POLICY)
    return v


# ── Schemas ─────────────────────────────────────────────────────────────────


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool
    created_at: str

    @classmethod
    def from_model(cls, u: UserModel) -> "UserResponse":
        return cls(
            id=str(u.id),
            email=u.email,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at.isoformat(),
        )


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = Field(default="staff")

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_password(v)
        return v


class SeedAdminRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)


# ── Bootstrap ────────────────────────────────────────────────────────────────


@router.post("/seed-admin", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def seed_admin(
    body: SeedAdminRequest,
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """Creates the first admin account. Fails if any user already exists."""
    result = await session.execute(select(UserModel))
    if result.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Users already exist. Use the admin panel to manage users.",
        )
    user = UserModel(
        id=str(uuid.uuid4()),
        email=body.email,
        hashed_password=hash_password(body.password),
        role="admin",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserResponse.from_model(user)


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[UserResponse])
async def list_users(
    _: Annotated[CurrentUser, Depends(require_admin)],
    session: AsyncSession = Depends(get_db_session),
) -> list[UserResponse]:
    result = await session.execute(select(UserModel).order_by(UserModel.created_at))
    return [UserResponse.from_model(u) for u in result.scalars().all()]


class UserDirectoryEntry(BaseModel):
    id: str
    email: str
    role: str


@router.get("/directory", response_model=list[UserDirectoryEntry])
async def user_directory(
    _: Annotated[CurrentUser, Depends(require_manager_or_above)],
    session: AsyncSession = Depends(get_db_session),
) -> list[UserDirectoryEntry]:
    """Lightweight user listing (id + email + role) for managers and above.

    Used by the dashboard to resolve operator UUIDs to human-readable names.
    """
    result = await session.execute(
        select(UserModel.id, UserModel.email, UserModel.role)
        .where(UserModel.is_active == True)  # noqa: E712
        .order_by(UserModel.email)
    )
    return [
        UserDirectoryEntry(id=str(row.id), email=row.email, role=row.role)
        for row in result.all()
    ]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    _: Annotated[CurrentUser, Depends(require_admin)],
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    if body.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of {ALLOWED_ROLES}")

    existing = await session.execute(select(UserModel).where(UserModel.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = UserModel(
        id=str(uuid.uuid4()),
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserResponse.from_model(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_admin: Annotated[CurrentUser, Depends(require_admin)],
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent admin from locking themselves out
    if user.id == current_admin.id and body.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    if user.id == current_admin.id and body.role and body.role != "admin":
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    if body.role is not None:
        if body.role not in ALLOWED_ROLES:
            raise HTTPException(status_code=400, detail=f"Role must be one of {ALLOWED_ROLES}")
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        user.hashed_password = hash_password(body.password)

    await session.commit()
    await session.refresh(user)
    return UserResponse.from_model(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_admin: Annotated[CurrentUser, Depends(require_admin)],
    session: AsyncSession = Depends(get_db_session),
) -> None:
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await session.delete(user)
    await session.commit()
