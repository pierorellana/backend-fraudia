from datetime import datetime

from pydantic import BaseModel


class HealthStatusRead(BaseModel):
    status: str
    service: str
    environment: str
    api_prefix: str
    database_health_url: str
    timestamp: datetime


class DatabaseHealthRead(BaseModel):
    connected: bool
    latency_ms: float | None = None
    database_backend: str
    checked_at: datetime
    error: str | None = None
