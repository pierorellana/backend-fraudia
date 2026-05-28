from __future__ import annotations

from datetime import UTC
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.domain import ChatMessage
from app.models.domain import ChatSession
from app.models.domain import Claim
from app.models.domain import ClaimDocument
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.repositories.claims import ClaimRepository
from app.schemas.agent import AgentResponse
from app.services.analytics_service import AnalyticsService
from app.services.ollama_client import OllamaClient
from app.services.risk_engine import normalize_text


class AgentService:
    def __init__(
        self,
        claims: ClaimRepository | None = None,
        analytics: AnalyticsService | None = None,
        ollama: OllamaClient | None = None,
    ) -> None:
        self.claims = claims or ClaimRepository()
        self.analytics = analytics or AnalyticsService()
        self.ollama = ollama or OllamaClient()

    def answer(
        self,
        db: Session,
        *,
        question: str,
        claim_id: str | None,
        session_id: str | None = None,
        user_id: str | None = None,
        use_llm: bool | None,
    ) -> AgentResponse:
        session = self._get_or_create_session(
            db,
            claim_id=claim_id,
            session_id=session_id,
            user_id=user_id,
            question=question,
        )
        resolved_claim_id = session.claim_id if session else claim_id
        history = self._recent_messages(db, session.id) if session else []
        context, sources = self._build_context(
            db,
            question=question,
            claim_id=resolved_claim_id,
            history=history,
        )
        should_use_llm = settings.ollama_enabled if use_llm is None else use_llm
        if should_use_llm:
            llm_answer = self.ollama.chat(question=question, context=context)
            if llm_answer:
                self._store_exchange(db, session=session, question=question, answer=llm_answer)
                return AgentResponse(
                    answer=llm_answer,
                    session_id=session.id if session else None,
                    claim_id=resolved_claim_id,
                    sources=sources,
                    used_llm=True,
                )

        answer = self._deterministic_answer(db, question=question, claim_id=resolved_claim_id)
        self._store_exchange(db, session=session, question=question, answer=answer)
        return AgentResponse(
            answer=answer,
            session_id=session.id if session else None,
            claim_id=resolved_claim_id,
            sources=sources,
        )

    def _get_or_create_session(
        self,
        db: Session,
        *,
        claim_id: str | None,
        session_id: str | None,
        user_id: str | None,
        question: str,
    ) -> ChatSession | None:
        now = self._utc_now()
        claim = self.claims.get_by_identifier(db, claim_id) if claim_id else None
        if claim_id and not claim:
            raise ValueError(f"No encontre el siniestro {claim_id}.")
        resolved_claim_id = claim.id if claim else None

        if session_id:
            session = db.get(ChatSession, session_id)
            if not session:
                raise ValueError(f"Sesion de chat no encontrada: {session_id}.")
            if resolved_claim_id and session.claim_id and session.claim_id != resolved_claim_id:
                raise ValueError(
                    f"La sesion {session_id} pertenece al siniestro {session.claim_id}, no a {claim_id}."
                )
            if resolved_claim_id and not session.claim_id:
                session.claim_id = resolved_claim_id
            session.updated_at = now
            db.flush()
            return session

        if resolved_claim_id:
            session = self._find_session_for_claim(db, resolved_claim_id)
            if session:
                session.updated_at = now
                db.flush()
                return session

            resolved_user_id = self._resolve_user_id(db, user_id)
            session = ChatSession(
                id=str(uuid4()),
                user_id=resolved_user_id,
                title=question[:160],
                created_at=now,
                updated_at=now,
                active_filters={"id_siniestro": resolved_claim_id},
                active=True,
            )
            db.add(session)
            db.flush()
            return session

        return None

    def _resolve_user_id(self, db: Session, user_id: str | None) -> str | None:
        if user_id:
            return user_id
        if settings.agent_default_user_id:
            return settings.agent_default_user_id

        try:
            resolved_user_id = db.execute(text("SELECT id_usuario FROM usuarios LIMIT 1")).scalar_one_or_none()
        except SQLAlchemyError:
            db.rollback()
            if db.bind and db.bind.dialect.name == "sqlite":
                return None
            raise ValueError(
                "No pude leer la tabla usuarios para crear la sesion de chat. "
                "Envia user_id en el body o configura AGENT_DEFAULT_USER_ID."
            )

        if not resolved_user_id:
            raise ValueError(
                "No encontre usuarios para crear la sesion de chat. "
                "Envia user_id en el body o configura AGENT_DEFAULT_USER_ID."
            )
        return str(resolved_user_id)

    def _find_session_for_claim(self, db: Session, claim_id: str) -> ChatSession | None:
        sessions = db.scalars(
            select(ChatSession)
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            .limit(100)
        ).all()
        for session in sessions:
            if session.active is not False and session.claim_id == claim_id:
                return session
        return None

    def _recent_messages(self, db: Session, session_id: str, *, limit: int = 10) -> list[ChatMessage]:
        messages = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        ).all()
        return list(reversed(messages))

    def _store_exchange(
        self,
        db: Session,
        *,
        session: ChatSession | None,
        question: str,
        answer: str,
    ) -> None:
        if not session:
            return

        now = self._utc_now()
        db.add_all(
            [
                ChatMessage(
                    id=str(uuid4()),
                    session_id=session.id,
                    role="user",
                    content=question,
                    created_at=now,
                ),
                ChatMessage(
                    id=str(uuid4()),
                    session_id=session.id,
                    role="assistant",
                    content=answer,
                    created_at=now,
                ),
            ]
        )
        session.updated_at = now
        db.commit()

    def _utc_now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def _build_context(
        self,
        db: Session,
        *,
        question: str,
        claim_id: str | None,
        history: list[ChatMessage] | None = None,
    ) -> tuple[str, list[str]]:
        lines: list[str] = []
        sources = ["scores_fraude", "alertas", "siniestros"]

        if history:
            sources.extend(["sesiones_chat", "mensajes_chat"])
            lines.append("Historial reciente de la conversacion:")
            for message in history:
                role = "Analista" if message.role == "user" else "Agente"
                lines.append(f"{role}: {message.content}")
            lines.append("Fin del historial reciente.")

        if claim_id:
            claim = self.claims.get_by_id(db, claim_id)
            if claim:
                lines.extend(self._claim_lines(claim))
                return "\n".join(lines), sources

        summary = self.analytics.dashboard_summary(db)
        lines.append(
            "Resumen: "
            f"{summary.total_claims} siniestros, {summary.assessed_claims} evaluados, "
            f"score promedio {summary.average_score}, monto alto riesgo {summary.high_risk_amount}."
        )

        top_claims = self.claims.top_risk(db, limit=10)
        lines.append("Top siniestros por riesgo:")
        for claim in top_claims:
            assessment = claim.risk_assessment
            if assessment:
                lines.append(f"- {self._claim_label(claim)}: score {assessment.score}, nivel {assessment.level}.")

        providers = self.analytics.provider_ranking(db, limit=5)
        lines.append("Proveedores con mayor riesgo promedio:")
        for provider in providers:
            lines.append(
                f"- {provider.provider_name}: score promedio {provider.average_score}, "
                f"{provider.high_risk_claims} casos altos."
            )

        return "\n".join(lines), sources

    def _deterministic_answer(self, db: Session, *, question: str, claim_id: str | None) -> str:
        normalized = normalize_text(question)

        if claim_id:
            claim = self.claims.get_by_id(db, claim_id)
            if not claim:
                return f"No encontre el siniestro {claim_id}."
            return self._explain_claim(claim)

        if "proveedor" in normalized:
            providers = self.analytics.provider_ranking(db, limit=10)
            if not providers:
                return "No hay proveedores con siniestros evaluados todavia."
            rows = [
                f"{index}. {provider.provider_name}: score promedio {provider.average_score}, "
                f"{provider.high_risk_claims} casos altos, {provider.total_claims} siniestros."
                for index, provider in enumerate(providers, start=1)
            ]
            return "Proveedores a revisar:\n" + "\n".join(rows)

        if "document" in normalized:
            return self._document_answer(db)

        if "monto" in normalized or "atipic" in normalized:
            return self._alert_based_answer(db, "RF-07", "Casos con montos atipicos")

        if "alerta" in normalized or "patron" in normalized:
            alerts = self.analytics.alert_ranking(db, limit=10)
            if not alerts:
                return "No hay alertas calculadas todavia."
            rows = [
                f"{index}. {alert.title}: {alert.occurrences} ocurrencias, {alert.total_points} puntos acumulados."
                for index, alert in enumerate(alerts, start=1)
            ]
            return "Patrones recurrentes detectados:\n" + "\n".join(rows)

        top_claims = self.claims.top_risk(db, limit=10)
        if not top_claims:
            return "No hay siniestros evaluados todavia. Carga datos y recalcula el riesgo primero."
        rows = []
        for index, claim in enumerate(top_claims, start=1):
            assessment = claim.risk_assessment
            if not assessment:
                continue
            rows.append(
                f"{index}. {self._claim_label(claim)}: score {assessment.score}, nivel {assessment.level}, "
                f"accion: {assessment.suggested_action}."
            )
        return "Casos recomendados para revisar primero:\n" + "\n".join(rows)

    def _claim_lines(self, claim: Claim) -> list[str]:
        lines = [
            f"Siniestro {self._claim_label(claim)}",
            f"Ramo/cobertura: {claim.branch} / {claim.coverage}",
            f"Monto reclamado: {claim.claimed_amount}",
            f"Descripcion: {claim.description or 'Sin descripcion'}",
        ]
        if claim.risk_assessment:
            assessment = claim.risk_assessment
            lines.append(
                f"Riesgo: score {assessment.score}, nivel {assessment.level}, "
                f"accion {assessment.suggested_action}."
            )
            for alert in assessment.alerts:
                lines.append(f"Alerta: {alert.title} (+{alert.points}) - {alert.description}")
        return lines

    def _explain_claim(self, claim: Claim) -> str:
        if not claim.risk_assessment:
            return f"El siniestro {self._claim_label(claim)} aun no tiene evaluacion de riesgo."

        assessment = claim.risk_assessment
        alerts = sorted(assessment.alerts, key=lambda alert: alert.points, reverse=True)
        alert_text = "\n".join(
            f"- {alert.title}: {alert.description} (+{alert.points})" for alert in alerts[:5]
        )
        return (
            f"El siniestro {self._claim_label(claim)} tiene score {assessment.score}/100 y nivel "
            f"{assessment.level}. Accion sugerida: {assessment.suggested_action}.\n"
            f"Motivos principales:\n{alert_text or '- Sin alertas relevantes.'}\n"
            "Esto no es una acusacion; es una priorizacion para revision humana."
        )

    def _document_answer(self, db: Session) -> str:
        rows = db.execute(
            select(Claim, ClaimDocument)
            .join(ClaimDocument, ClaimDocument.claim_id == Claim.id)
            .where(
                (ClaimDocument.delivered.is_(False))
                | (ClaimDocument.legible.is_(False))
                | (ClaimDocument.inconsistency_detected.is_(True))
            )
            .order_by(Claim.id)
            .limit(20)
        ).all()
        if not rows:
            return "No encontre documentos faltantes, ilegibles o inconsistentes."
        items = [
            f"- {claim.code or claim.id}: {document.document_type or document.id} ({document.status})"
            for claim, document in rows
        ]
        return "Documentos con novedades:\n" + "\n".join(items)

    def _alert_based_answer(self, db: Session, code: str, title: str) -> str:
        rows = db.scalars(
            select(Claim)
            .join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
            .join(RiskAlert, RiskAlert.assessment_id == RiskAssessment.id)
            .where(RiskAlert.code == code)
            .options(selectinload(Claim.risk_assessment))
            .order_by(RiskAssessment.score.desc())
            .limit(10)
        ).all()
        if not rows:
            return f"No encontre casos para: {title}."
        items = [
            f"- {self._claim_label(claim)}: score {claim.risk_assessment.score}, monto {claim.claimed_amount}"
            for claim in rows
            if claim.risk_assessment
        ]
        return f"{title}:\n" + "\n".join(items)

    def _claim_label(self, claim: Claim) -> str:
        return claim.code or claim.id
