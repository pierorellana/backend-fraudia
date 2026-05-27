from pydantic import BaseModel
from pydantic import Field


class AgentQuery(BaseModel):
    question: str = Field(min_length=3, max_length=800)
    claim_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    use_llm: bool | None = None


class AgentResponse(BaseModel):
    answer: str
    session_id: str | None = None
    claim_id: str | None = None
    sources: list[str] = []
    used_llm: bool = False
    disclaimer: str = "La respuesta es una alerta de apoyo analitico y requiere revision humana."
