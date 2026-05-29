from datetime import datetime

from pydantic import BaseModel
from pydantic import Field


class AgentQueryContext(BaseModel):
    risk_level: str | None = None
    claim_id: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


class AgentQuery(BaseModel):
    question: str = Field(min_length=3, max_length=1200)
    session_id: str | None = None
    user_id: str | None = None
    claim_id: str | None = None
    use_llm: bool | None = None
    context: AgentQueryContext = Field(default_factory=AgentQueryContext)


class AgentResponse(BaseModel):
    answer: str
    session_id: str | None = None
    claim_id: str | None = None
    sources: list[str] = Field(default_factory=list)
    used_llm: bool = False
    disclaimer: str = "La respuesta es una alerta de apoyo analitico y requiere revision humana."


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    claim_id: str | None = None
    user_id: str | None = None


class ChatSessionRead(BaseModel):
    id: str
    user_id: str | None = None
    title: str | None = None
    claim_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    active: bool = True


class ChatMessageRead(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    context_data: dict | None = None
    tokens_used: int | None = None
    created_at: datetime | None = None


class SuggestedQuestionRead(BaseModel):
    question: str
