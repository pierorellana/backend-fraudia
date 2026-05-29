from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import ChatMessage
from app.models.domain import ChatSession


class AgentRepository:
    def list_sessions(self, db: Session) -> list[ChatSession]:
        return list(
            db.scalars(
                select(ChatSession).order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            ).all()
        )

    def get_session(self, db: Session, session_id: str) -> ChatSession | None:
        return db.get(ChatSession, session_id)

    def list_messages(self, db: Session, session_id: str) -> list[ChatMessage]:
        return list(
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            ).all()
        )
