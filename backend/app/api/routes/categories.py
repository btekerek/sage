from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.handlers.category_handlers import CategoryCommandHandler
from app.core.db import get_db_session
from app.domain.commands.category_commands import CreateCategoryCommand

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_category_id: UUID | None = None


class CategoryWriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_id: UUID
    status: str


@router.post("", response_model=CategoryWriteResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CreateCategoryRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CategoryWriteResponse:
    handler = CategoryCommandHandler(session)
    if payload.parent_category_id is None:
        command = CreateCategoryCommand(name=payload.name)
    else:
        assert payload.parent_category_id is not None
        command = CreateCategoryCommand(
            name=payload.name,
            parent_category_id=payload.parent_category_id,
        )

    await handler.handle_create_category(command)

    if command.aggregate_id is None:
        raise RuntimeError("CreateCategoryCommand aggregate_id was not initialized")

    return CategoryWriteResponse(aggregate_id=command.aggregate_id, status="accepted")
