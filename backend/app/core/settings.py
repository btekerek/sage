from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(..., alias="DATABASE_URL")

    secret_key: str = Field(..., alias="SECRET_KEY", min_length=8)
    session_expire_seconds: int = Field(
        28800,
        alias="SESSION_EXPIRE_SECONDS",
        gt=0,
    )

    anthropic_api_key: Optional[str] = Field(None, alias="ANTHROPIC_API_KEY")
    ai_confidence_threshold: float = Field(
        0.85,
        alias="AI_CONFIDENCE_THRESHOLD",
        ge=0.0,
        le=1.0,
    )
    
    ocr_engine_path: str = Field(..., alias="OCR_ENGINE_PATH")

    replenishment_budget: float = Field(
        10000.0,
        alias="REPLENISHMENT_BUDGET",
        gt=0,
    )
    replenishment_target_days: int = Field(
        30,
        alias="REPLENISHMENT_TARGET_DAYS",
        gt=0,
    )
    costing_strategy: Literal["FIFO", "WAC"] = Field(
        "FIFO",
        alias="COSTING_STRATEGY",
    )

    @field_validator("costing_strategy", mode="before")
    @classmethod
    def normalize_costing_strategy(cls, value: object) -> str:
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {"FIFO", "WAC"}:
                return normalized
        raise ValueError("COSTING_STRATEGY must be FIFO or WAC")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()