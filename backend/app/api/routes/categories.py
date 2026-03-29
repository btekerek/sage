from uuid import UUID

from app.api.read_models import CategoryReadModel
from app.application.handlers.category_handlers import CategoryCommandHandler
from app.core.db import get_db_session
from app.domain.commands.category_commands import CreateCategoryCommand
from app.infrastructure.projectors.read_entities import CategoryReadEntity
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CreateCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_category_id: UUID | None = None


class CategoryWriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_id: UUID
    status: str


@router.post(
    "", response_model=CategoryWriteResponse, status_code=status.HTTP_201_CREATED
)
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


@router.get("/{category_id}", response_model=CategoryReadModel)
async def get_category(
    category_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> CategoryReadModel:
    """Retrieve a category from the read model."""
    stmt = select(CategoryReadEntity).where(CategoryReadEntity.id == category_id)
    result = await session.execute(stmt)
    entity = result.scalar_one_or_none()

    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    return CategoryReadModel.model_validate(entity)
