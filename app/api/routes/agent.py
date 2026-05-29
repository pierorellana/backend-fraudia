from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.agent import AgentQuery
from app.schemas.agent import AgentResponse
from app.schemas.agent import ChatMessageRead
from app.schemas.agent import ChatSessionCreate
from app.schemas.agent import ChatSessionRead
from app.schemas.agent import SuggestedQuestionRead
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.services.agent_service import AgentService

router = APIRouter()
agent_service = AgentService()


@router.post("/query", response_model=GeneralResponse[AgentResponse])
def query_agent(payload: AgentQuery, db: Session = Depends(get_db)) -> GeneralResponse[AgentResponse]:
    try:
        return success_response(
            agent_service.answer(
                db,
                question=payload.question,
                session_id=payload.session_id,
                user_id=payload.user_id,
                claim_id=payload.claim_id,
                use_llm=payload.use_llm,
                context=payload.context,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sessions", response_model=GeneralResponse[ChatSessionRead])
def create_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
) -> GeneralResponse[ChatSessionRead]:
    try:
        session = agent_service.create_session(
            db,
            title=payload.title,
            claim_id=payload.claim_id,
            user_id=payload.user_id,
        )
        return success_response(ChatSessionRead.model_validate(session, from_attributes=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sessions", response_model=GeneralResponse[list[ChatSessionRead]])
def list_sessions(db: Session = Depends(get_db)) -> GeneralResponse[list[ChatSessionRead]]:
    return success_response(
        [ChatSessionRead.model_validate(item, from_attributes=True) for item in agent_service.list_sessions(db)]
    )


@router.get("/sessions/{session_id}/messages", response_model=GeneralResponse[list[ChatMessageRead]])
def list_messages(
    session_id: str,
    db: Session = Depends(get_db),
) -> GeneralResponse[list[ChatMessageRead]]:
    try:
        return success_response(
            [ChatMessageRead.model_validate(item, from_attributes=True) for item in agent_service.list_messages(db, session_id)]
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/suggested-questions", response_model=GeneralResponse[list[SuggestedQuestionRead]])
def suggested_questions() -> GeneralResponse[list[SuggestedQuestionRead]]:
    return success_response(agent_service.suggested_questions())


@router.post("/claims/{claim_id}/explain", response_model=GeneralResponse[AgentResponse])
def explain_claim(claim_id: str, db: Session = Depends(get_db)) -> GeneralResponse[AgentResponse]:
    try:
        return success_response(agent_service.explain_claim(db, claim_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
