from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ASUR AntiFraud API"
    environment: str = "local"
    api_prefix: str = "/api"
    auto_create_tables: bool = True

    database_url: str = Field(
        default="postgresql+psycopg://asur:asur@localhost:5432/asur_antifraude",
        description="SQLAlchemy database URL. Use PostgreSQL in production.",
    )

    cors_origins: str = "http://localhost:4200,http://127.0.0.1:4200"

    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_embeddings_enabled: bool = False
    ollama_embedding_model: str = "bge-m3"
    ollama_timeout_seconds: float = 45.0

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
