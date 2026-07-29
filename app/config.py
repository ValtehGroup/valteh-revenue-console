from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
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

    # Source-system operational-event export endpoints (pull model).
    # Each system exposes GET <base_url>/api/operational-events, cursor-paginated.
    baas_qro_events_url: str = Field(
        default="",
        description="Base URL of baas-qro, e.g. http://localhost:3334. Empty disables this source.",
    )
    baas_qro_events_token: str = Field(default="", description="Service token for baas-qro export endpoint.")
    rpp_events_url: str = Field(
        default="",
        description="Base URL of rpp-fraud-detection-system, e.g. http://localhost:3000. Empty disables this source.",
    )
    rpp_events_token: str = Field(default="", description="Service token for the rpp export endpoint.")
    events_sync_page_size: int = Field(default=200, description="Max events requested per export page.")

    revenue_api_token: str = Field(
        default="",
        description="Bearer token required on /api/v1/* requests. Empty disables auth (local development only).",
    )

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in {"release", "production", "prod"}:
            return False
        return value

    def event_sources(self) -> list["SourceConfig"]:
        """Return the configured (non-empty) operational-event sources."""

        sources: list[SourceConfig] = []
        if self.baas_qro_events_url:
            sources.append(
                SourceConfig(
                    source_system="baas-qro",
                    base_url=self.baas_qro_events_url,
                    token=self.baas_qro_events_token,
                    page_size=self.events_sync_page_size,
                )
            )
        if self.rpp_events_url:
            sources.append(
                SourceConfig(
                    source_system="rpp-fraud-detection-system",
                    base_url=self.rpp_events_url,
                    token=self.rpp_events_token,
                    page_size=self.events_sync_page_size,
                )
            )
        return sources


class SourceConfig(BaseModel):
    """Connection details for one operational-event source system."""

    source_system: str
    base_url: str
    token: str = ""
    page_size: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
