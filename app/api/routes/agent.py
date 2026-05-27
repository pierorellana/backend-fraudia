from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.agent import AgentQuery
from app.schemas.agent import AgentResponse
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.services.agent_service import AgentService

router = APIRouter()
agent_service = AgentService()


@router.post("/query", response_model=GeneralResponse[AgentResponse])
def query_agent(payload: AgentQuery, db: Session = Depends(get_db)) -> GeneralResponse[AgentResponse]:
    return success_response(
        agent_service.answer(
            db,
            question=payload.question,
            claim_id=payload.claim_id,
            use_llm=payload.use_llm,
        )
    )
