from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "Valteh Economics Dashboard"
    environment: str = "development"
    debug: bool = True
    database_url: str = Field(
        default=f"sqlite:///{BASE_DIR / 'valteh_economics.db'}",
        description="SQLAlchemy database URL. Use PostgreSQL URL in production.",
    )
    seed_data_dir: Path = BASE_DIR / "data"
    currency: str = "MXN"

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in {"release", "production", "prod"}:
            return False
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
