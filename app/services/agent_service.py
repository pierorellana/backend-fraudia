from __future__ import annotations

from datetime import UTC
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import ChatMessage
from app.models.domain import ChatSession
from app.repositories.agent import AgentRepository
from app.repositories.claims import ClaimRepository
from app.schemas.agent import AgentQueryContext
from app.schemas.agent import AgentResponse
from app.services.analytics_service import AnalyticsService
from app.services.ollama_client import OllamaClient
from app.services.risk_engine import ETHICAL_DISCLAIMER
from app.services.risk_engine import normalize_text


SUGGESTED_QUESTIONS = [
    "Dame un resumen ejecutivo del tablero de riesgo.",
    "Cuales son los siniestros con mayor riesgo hoy?",
    "Por que este siniestro fue marcado con alerta?",
    "Que proveedores concentran mas alertas?",
    "Que documentos faltantes debo revisar primero?",
]


class AgentService:
    def __init__(
        self,
        claims: ClaimRepository | None = None,
        analytics: AnalyticsService | None = None,
        ollama: OllamaClient | None = None,
        repository: AgentRepository | None = None,
    ) -> None:
        self.claims = claims or ClaimRepository()
        self.analytics = analytics or AnalyticsService()
        self.ollama = ollama or OllamaClient()
        self.repository = repository or AgentRepository()

    def answer(
        self,
        db: Session,
        *,
        question: str,
        session_id: str | None = None,
        user_id: str | None = None,
        claim_id: str | None = None,
        use_llm: bool | None = None,
        context: AgentQueryContext | None = None,
    ) -> AgentResponse:
        session = self._resolve_session(db, session_id=session_id, user_id=user_id, claim_id=claim_id, question=question)
        raw_claim_identifier = claim_id or (context.claim_id if context else None) or (session.claim_id if session else None)
        resolved_claim_id = raw_claim_identifier
        if raw_claim_identifier:
            claim = self.claims.get_by_identifier(db, raw_claim_identifier)
            if claim:
                resolved_claim_id = claim.id
        context = context or AgentQueryContext()
        controlled_context, sources = self._build_controlled_context(
            db,
            question=question,
            claim_id=resolved_claim_id,
            risk_level=context.risk_level,
            limit=context.limit,
        )

        should_use_llm = settings.ollama_enabled if use_llm is None else use_llm
        answer = None
        used_llm = False
        if should_use_llm:
            answer = self.ollama.chat(question=question, context=controlled_context)
            used_llm = bool(answer)

        if not answer:
            answer = self._deterministic_answer(
                db,
                question=question,
                claim_id=resolved_claim_id,
                risk_level=context.risk_level,
                limit=context.limit,
            )

        if ETHICAL_DISCLAIMER not in answer:
            answer = f"{answer}\n\n{ETHICAL_DISCLAIMER}"

        if session:
            self._store_exchange(db, session=session, question=question, answer=answer)

        return AgentResponse(
            answer=answer,
            session_id=session.id if session else None,
            claim_id=resolved_claim_id,
            sources=sources,
            used_llm=used_llm,
            disclaimer=ETHICAL_DISCLAIMER,
        )

    def create_session(
        self,
        db: Session,
        *,
        title: str | None,
        claim_id: str | None,
        user_id: str | None,
    ) -> ChatSession:
        session = ChatSession(
            id=str(uuid4()),
            user_id=user_id,
            title=title or "Sesion de analisis",
            created_at=self._utc_now(),
            updated_at=self._utc_now(),
            active_filters={},
            active=True,
        )
        if claim_id:
            claim = self.claims.get_by_identifier(db, claim_id)
            if not claim:
                raise ValueError(f"No encontre el siniestro {claim_id}.")
            session.claim_id = claim.id
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def list_sessions(self, db: Session) -> list[ChatSession]:
        return self.repository.list_sessions(db)

    def list_messages(self, db: Session, session_id: str) -> list[ChatMessage]:
        session = self.repository.get_session(db, session_id)
        if not session:
            raise ValueError(f"Sesion de chat no encontrada: {session_id}.")
        return self.repository.list_messages(db, session_id)

    def suggested_questions(self) -> list[dict]:
        return [{"question": item} for item in SUGGESTED_QUESTIONS]

    def explain_claim(self, db: Session, claim_id: str) -> AgentResponse:
        return self.answer(
            db,
            question="Explica por que este siniestro fue marcado.",
            claim_id=claim_id,
            use_llm=False,
            context=AgentQueryContext(claim_id=claim_id, limit=5),
        )

    def _resolve_session(
        self,
        db: Session,
        *,
        session_id: str | None,
        user_id: str | None,
        claim_id: str | None,
        question: str,
    ) -> ChatSession | None:
        if session_id:
            session = self.repository.get_session(db, session_id)
            if not session:
                raise ValueError(f"Sesion de chat no encontrada: {session_id}.")
            if claim_id:
                claim = self.claims.get_by_identifier(db, claim_id)
                if not claim:
                    raise ValueError(f"No encontre el siniestro {claim_id}.")
                session.claim_id = claim.id
            session.updated_at = self._utc_now()
            db.add(session)
            db.commit()
            return session

        if not claim_id:
            return None
        claim = self.claims.get_by_identifier(db, claim_id)
        if not claim:
            raise ValueError(f"No encontre el siniestro {claim_id}.")
        session = ChatSession(
            id=str(uuid4()),
            user_id=user_id,
            title=question[:160],
            created_at=self._utc_now(),
            updated_at=self._utc_now(),
            active_filters={"id_siniestro": claim.id, "claim_id": claim.id},
            active=True,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def _build_controlled_context(
        self,
        db: Session,
        *,
        question: str,
        claim_id: str | None,
        risk_level: str | None,
        limit: int,
    ) -> tuple[str, list[str]]:
        normalized = normalize_text(question)
        sources = ["siniestros", "scores_fraude", "alertas"]

        if claim_id:
            claim = self.claims.get_by_identifier(db, claim_id)
            if not claim:
                return f"No existe el siniestro {claim_id}.", sources
            lines = [
                f"Siniestro: {claim.code or claim.id}",
                f"Ramo: {claim.branch}",
                f"Cobertura: {claim.coverage}",
                f"Monto reclamado: {claim.claimed_amount}",
                f"Estado de flujo: {claim.flow_status}",
                f"Descripcion: {claim.description or 'Sin descripcion'}",
            ]
            if claim.risk_assessment:
                lines.append(
                    f"Score total: {claim.risk_assessment.score}; nivel: {claim.risk_assessment.level}; "
                    f"recomendacion: {claim.risk_assessment.recommendation}"
                )
                for alert in claim.risk_assessment.alerts:
                    lines.append(
                        f"Alerta {alert.code}: {alert.title}; puntos={alert.points}; detalle={alert.description}"
                    )
            return "\n".join(lines), sources

        if "proveedor" in normalized:
            sources.append("proveedores")
            ranking = self.analytics.provider_ranking(db, limit=limit)
            lines = ["Proveedores con mayor concentracion de alertas:"]
            for provider in ranking:
                lines.append(
                    f"{provider.provider_name}: alertas={provider.total_alerts}, "
                    f"score_promedio={provider.average_score}, altos={provider.high_risk_claims}"
                )
            return "\n".join(lines), sources

        if "document" in normalized:
            rows = []
            for claim in self.claims.top_risk(db, limit=limit):
                for document in claim.documents:
                    if not document.delivered or not document.legible or document.inconsistency_detected:
                        rows.append(
                            f"{claim.code or claim.id}: {document.document_type or document.code} - {document.status}"
                        )
            lines = ["Documentos con novedad:"] + rows[:limit]
            return "\n".join(lines), sources

        if "resumen" in normalized or "ejecutivo" in normalized:
            summary = self.analytics.dashboard_summary(db)
            top_claims = self.claims.top_risk_summary(db, limit=limit)
            alerts = self.analytics.alert_ranking(db, limit=5)
            lines = [
                f"Resumen ejecutivo: total_claims={summary.total_claims}, assessed={summary.assessed_claims}, "
                f"alto_riesgo={summary.casos_alto_riesgo}, score_promedio={summary.average_score}.",
                "Top siniestros:",
            ]
            for claim in top_claims:
                lines.append(
                    f"{claim['code']}: score={claim['score_total']}, nivel={claim['nivel_riesgo']}, alertas={claim['total_alertas']}"
                )
            lines.append("Alertas recurrentes:")
            for alert in alerts:
                lines.append(f"{alert.code}: {alert.occurrences} ocurrencias, {alert.total_points} puntos")
            return "\n".join(lines), sources

        top_claims = self.claims.top_risk_summary(db, limit=limit)
        if risk_level:
            top_claims = [claim for claim in top_claims if str(claim["nivel_riesgo"]).lower() == risk_level.lower()]
        lines = ["Top siniestros por riesgo:"]
        for claim in top_claims:
            lines.append(
                f"{claim['code']}: score={claim['score_total']}, nivel={claim['nivel_riesgo']}, "
                f"monto={claim['monto_reclamado']}"
            )
        return "\n".join(lines), sources

    def _deterministic_answer(
        self,
        db: Session,
        *,
        question: str,
        claim_id: str | None,
        risk_level: str | None,
        limit: int,
    ) -> str:
        normalized = normalize_text(question)
        if claim_id:
            claim = self.claims.get_by_identifier(db, claim_id)
            if not claim:
                return f"No encontre el siniestro {claim_id}."
            if not claim.risk_assessment:
                return (
                    f"El siniestro {claim.code or claim.id} aun no tiene evaluacion automatica. "
                    "Primero ejecuta la evaluacion del caso."
                )
            alerts = sorted(claim.risk_assessment.alerts, key=lambda item: item.points or 0, reverse=True)
            reasons = "\n".join(
                f"- {alert.title}: {alert.description} (+{alert.points})"
                for alert in alerts[:5]
            )
            return (
                f"El siniestro {claim.code or claim.id} fue marcado con score {claim.risk_assessment.score}/100 "
                f"y nivel {claim.risk_assessment.level}.\n"
                f"Explicacion: {claim.risk_assessment.explanation}\n"
                f"Alertas principales:\n{reasons or '- Sin alertas relevantes.'}"
            )

        if "proveedor" in normalized:
            providers = self.analytics.provider_ranking(db, limit=limit)
            if not providers:
                return "No hay proveedores con alertas acumuladas todavia."
            return "\n".join(
                [
                    "Proveedores con mayor concentracion de alertas:",
                    *[
                        f"{index}. {provider.provider_name}: alertas={provider.total_alerts}, "
                        f"score_promedio={provider.average_score}, casos_altos={provider.high_risk_claims}"
                        for index, provider in enumerate(providers, start=1)
                    ],
                ]
            )

        if "document" in normalized:
            lines = ["Documentos faltantes o inconsistentes a revisar primero:"]
            total = 0
            for claim in self.claims.top_risk(db, limit=limit):
                for document in claim.documents:
                    if not document.delivered or not document.legible or document.inconsistency_detected:
                        lines.append(
                            f"- {claim.code or claim.id}: {document.document_type or document.code} ({document.status})"
                        )
                        total += 1
                        if total >= limit:
                            return "\n".join(lines)
            return "\n".join(lines) if total else "No encontre documentos faltantes o inconsistentes."

        if "resumen" in normalized or "ejecutivo" in normalized:
            summary = self.analytics.dashboard_summary(db)
            providers = self.analytics.provider_ranking(db, limit=3)
            alerts = self.analytics.alert_ranking(db, limit=3)
            lines = [
                f"Resumen ejecutivo: {summary.total_claims} siniestros, {summary.assessed_claims} evaluados, "
                f"{summary.casos_alto_riesgo} en rojo y score promedio {summary.average_score}.",
                "Proveedores a vigilar:",
            ]
            lines.extend(
                f"- {provider.provider_name}: {provider.total_alerts} alertas, score promedio {provider.average_score}"
                for provider in providers
            )
            lines.append("Reglas mas activadas:")
            lines.extend(f"- {alert.title}: {alert.occurrences} ocurrencias" for alert in alerts)
            return "\n".join(lines)

        top_claims = self.claims.top_risk_summary(db, limit=limit)
        if risk_level:
            top_claims = [claim for claim in top_claims if str(claim["nivel_riesgo"]).lower() == risk_level.lower()]
        if not top_claims:
            return "No hay siniestros evaluados para ese criterio."
        return "\n".join(
            [
                "Siniestros con mayor prioridad de revision:",
                *[
                    f"{index}. {claim['code']}: score={claim['score_total']}, nivel={claim['nivel_riesgo']}, "
                    f"alertas={claim['total_alertas']}"
                    for index, claim in enumerate(top_claims, start=1)
                ],
            ]
        )

    def _store_exchange(self, db: Session, *, session: ChatSession, question: str, answer: str) -> None:
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
        db.add(session)
        db.commit()

    def _utc_now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
