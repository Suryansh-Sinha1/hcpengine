from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_prefix="HCP_",
        extra="ignore",
    )

    # Language model
    ollama_model: str = "llama3.1:8b"
    ollama_num_ctx: int = 4096
    generation_temperature: float = 0.2

    # Data
    claims_dir: Path = BACKEND_ROOT / "data" / "claims"
    database_path: Path = BACKEND_ROOT / "data" / "decisions.db"

    # Workflow
    max_attempts: int = 3

    # Compliance posture
    strict_verification: bool = False
    judge_can_block: bool = False

    # API
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()