from __future__ import annotations

from datetime import UTC
from datetime import datetime
import re
from uuid import UUID
from uuid import uuid4

from sqlalchemy import or_
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


CLAIM_ID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


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
        should_use_llm = self._should_use_llm(use_llm)
        sources = ["scores_fraude", "alertas", "siniestros"]
        quick_reply = self._quick_conversation_reply(db, question=question, claim_id=resolved_claim_id)
        if quick_reply:
            quick_answer, quick_sources = quick_reply
            self._store_exchange(db, session=session, question=question, answer=quick_answer)
            return AgentResponse(
                answer=quick_answer,
                session_id=session.id if session else None,
                claim_id=resolved_claim_id,
                sources=quick_sources,
            )

        fast_claim_answer = self._fast_claim_answer(db, question=question, claim_id=resolved_claim_id)
        if fast_claim_answer:
            self._store_exchange(db, session=session, question=question, answer=fast_claim_answer)
            return AgentResponse(
                answer=fast_claim_answer,
                session_id=session.id if session else None,
                claim_id=resolved_claim_id,
                sources=sources,
            )

        if should_use_llm:
            history = (
                self._recent_messages(db, session.id, limit=settings.agent_history_limit)
                if session
                else []
            )
            context, sources = self._build_context(
                db,
                question=question,
                claim_id=resolved_claim_id,
                history=history,
            )
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

    def _should_use_llm(self, use_llm: bool | None) -> bool:
        if use_llm is not None:
            return use_llm and settings.ollama_enabled
        return settings.ollama_enabled and settings.agent_llm_default_enabled

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
        resolved_claim_id = self._resolve_claim_id(db, claim_id) if claim_id else None

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
            return self._validated_user_id(db, user_id, source="user_id")
        if settings.agent_default_user_id:
            return self._validated_user_id(db, settings.agent_default_user_id, source="AGENT_DEFAULT_USER_ID")

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

    def _validated_user_id(self, db: Session, user_id: str, *, source: str) -> str:
        normalized_user_id = user_id.strip()
        try:
            UUID(normalized_user_id)
        except ValueError as exc:
            raise ValueError(f"{source} debe ser un UUID valido.") from exc

        try:
            exists = db.execute(
                text("SELECT 1 FROM usuarios WHERE id_usuario = :user_id LIMIT 1"),
                {"user_id": normalized_user_id},
            ).scalar_one_or_none()
        except SQLAlchemyError as exc:
            db.rollback()
            if db.bind and db.bind.dialect.name == "sqlite":
                return normalized_user_id
            raise ValueError(
                f"No pude validar {source} contra la tabla usuarios. "
                "Envia un user_id existente o configura AGENT_DEFAULT_USER_ID."
            ) from exc

        if not exists:
            raise ValueError(
                f"Usuario no encontrado: {normalized_user_id}. "
                "Envia un user_id existente en la tabla usuarios o no envies user_id."
            )
        return normalized_user_id

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
                lines.append(f"{role}: {self._clip(message.content, 600)}")
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
            return self._answer_claim_question(db, claim=claim, normalized_question=normalized)

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

    def _quick_conversation_reply(
        self,
        db: Session,
        *,
        question: str,
        claim_id: str | None,
    ) -> tuple[str, list[str]] | None:
        normalized = normalize_text(question).strip()
        if not normalized:
            return None

        claim_label = self._claim_label_from_id(db, claim_id) if claim_id else None
        sources = ["siniestros"] if claim_label else []
        if self._is_greeting(normalized):
            if claim_label:
                return (
                    f"Hola. Tengo en contexto el siniestro {claim_label}. "
                    "Puedo ayudarte a explicar el riesgo, preparar un resumen ejecutivo, "
                    "revisar documentos o priorizar los siguientes pasos.",
                    sources,
                )
            return (
                "Hola. Soy el agente de apoyo antifraude. "
                "Puedo ayudarte a priorizar casos, explicar alertas, revisar proveedores, "
                "documentos o montos atipicos.",
                sources,
            )

        if self._is_thanks(normalized):
            if claim_label:
                return (
                    f"Con gusto. Sigo con el siniestro {claim_label} en contexto. "
                    "Puedes pedirme motivos, documentos, resumen ejecutivo o proximos pasos.",
                    sources,
                )
            return (
                "Con gusto. Cuando quieras, puedo ayudarte a revisar riesgos, alertas o proveedores.",
                sources,
            )

        if self._is_help_request(normalized):
            return self._help_answer(claim_label), sources

        if self._is_out_of_scope(normalized):
            return self._out_of_scope_answer(normalized, claim_label), sources

        return None

    def _resolve_claim_id(self, db: Session, claim_id: str) -> str:
        normalized_identifier = claim_id.strip()
        filters = [Claim.code == normalized_identifier.upper()]
        if self._is_uuid(normalized_identifier):
            filters.append(Claim.id == normalized_identifier)

        resolved_claim_id = db.scalar(select(Claim.id).where(or_(*filters)).limit(1))
        if not resolved_claim_id:
            raise ValueError(f"No encontre el siniestro {claim_id}.")
        return str(resolved_claim_id)

    def _answer_claim_question(self, db: Session, *, claim: Claim, normalized_question: str) -> str:
        if self._is_summary_request(normalized_question):
            return self._explain_claim(db, claim)
        if self._is_next_steps_request(normalized_question):
            return self._claim_next_steps_answer(claim)
        if self._is_document_request(normalized_question):
            return self._claim_documents_answer(claim)
        if self._is_status_request(normalized_question):
            return self._claim_status_answer(claim)
        if self._is_reason_request(normalized_question):
            return self._claim_reasons_answer(db, claim)
        return self._claim_overview_answer(claim)

    def _claim_lines(self, claim: Claim) -> list[str]:
        lines = [
            f"Siniestro {self._claim_label(claim)}",
            f"Ramo/cobertura: {claim.branch} / {claim.coverage}",
            f"Monto reclamado: {claim.claimed_amount}",
            f"Descripcion: {self._clip(claim.description or 'Sin descripcion', 700)}",
        ]
        if claim.risk_assessment:
            assessment = claim.risk_assessment
            lines.append(
                f"Riesgo: score {assessment.score}, nivel {assessment.level}, "
                f"accion {assessment.suggested_action}."
            )
            alerts = sorted(assessment.alerts, key=lambda alert: alert.points or 0, reverse=True)
            for alert in alerts[:8]:
                lines.append(
                    f"Alerta: {alert.title} (+{alert.points}) - "
                    f"{self._clip(alert.description or '', 220)}"
                )
        return lines

    def _is_greeting(self, normalized: str) -> bool:
        cleaned = re.sub(r"[^a-z0-9 ]+", " ", normalized).strip()
        tokens = cleaned.split()
        if not tokens or len(tokens) > 4:
            return False
        greetings = {
            "hola",
            "buenas",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "hey",
            "ola",
        }
        return cleaned in greetings or tokens[0] in {"hola", "buenas", "hey", "ola"}

    def _is_thanks(self, normalized: str) -> bool:
        cleaned = re.sub(r"[^a-z0-9 ]+", " ", normalized).strip()
        tokens = cleaned.split()
        if not tokens or len(tokens) > 6:
            return False
        return any(token in {"gracias", "listo", "ok", "perfecto"} for token in tokens)

    def _is_help_request(self, normalized: str) -> bool:
        return any(
            phrase in normalized
            for phrase in (
                "que puedes hacer",
                "como me ayudas",
                "ayuda",
                "opciones",
                "que sabes hacer",
                "comandos",
            )
        )

    def _is_out_of_scope(self, normalized: str) -> bool:
        if self._has_domain_terms(normalized):
            return False

        math_patterns = (
            r"\bcuanto es\b",
            r"\bsuma de\b",
            r"\bresta de\b",
            r"\bmultiplica\b",
            r"\bdivide\b",
            r"\braiz cuadrada\b",
            r"\bcalcula\b",
            r"\b[0-9]+\s*[\+\-\*/]\s*[0-9]+\b",
        )
        if any(re.search(pattern, normalized) for pattern in math_patterns):
            return True

        out_of_scope_terms = {
            "css",
            "html",
            "javascript",
            "typescript",
            "react",
            "angular",
            "vue",
            "python",
            "java",
            "programacion",
            "codigo",
            "div",
            "centrar",
            "capital",
            "clima",
            "receta",
            "chiste",
            "poema",
            "cancion",
            "traduce",
            "historia",
            "deporte",
            "futbol",
            "presidente",
            "pelicula",
            "restaurante",
            "viaje",
        }
        tokens = set(re.findall(r"[a-z0-9]+", normalized))
        if tokens & out_of_scope_terms:
            return True

        off_domain_phrases = (
            "como centro",
            "como hacer",
            "como programar",
            "dame una receta",
            "cuentame un chiste",
            "quien es",
            "que es la capital",
            "hablame de",
        )
        return any(phrase in normalized for phrase in off_domain_phrases)

    def _has_domain_terms(self, normalized: str) -> bool:
        return any(
            term in normalized
            for term in (
                "siniestro",
                "reclamo",
                "caso",
                "riesgo",
                "fraude",
                "alerta",
                "score",
                "proveedor",
                "document",
                "soporte",
                "monto reclamado",
                "monto atipico",
                "suma asegurada",
                "poliza",
                "asegurado",
                "vehiculo",
                "cobertura",
                "denuncia",
                "reporte",
                "revision",
                "resumen ejecutivo",
            )
        )

    def _is_summary_request(self, normalized: str) -> bool:
        return any(
            phrase in normalized
            for phrase in (
                "resumen ejecutivo",
                "resumen",
                "sintesis",
                "informe",
                "supervisor",
                "gerencia",
            )
        )

    def _is_next_steps_request(self, normalized: str) -> bool:
        return any(
            phrase in normalized
            for phrase in (
                "que debo revisar",
                "que revisar",
                "revisar primero",
                "siguiente paso",
                "siguientes pasos",
                "proximos pasos",
                "accion",
                "acciones",
                "recomendacion",
                "recomendaciones",
            )
        )

    def _is_document_request(self, normalized: str) -> bool:
        return any(term in normalized for term in ("document", "soporte", "archivo", "adjunto"))

    def _is_status_request(self, normalized: str) -> bool:
        return any(
            phrase in normalized
            for phrase in (
                "score",
                "nivel",
                "estado",
                "riesgo actual",
                "cuanto riesgo",
                "calificacion",
            )
        )

    def _is_reason_request(self, normalized: str) -> bool:
        return any(
            phrase in normalized
            for phrase in (
                "por que",
                "porque",
                "motivo",
                "motivos",
                "razon",
                "razones",
                "marcado",
                "alto riesgo",
                "alertas",
                "explica",
                "explicame",
            )
        )

    def _help_answer(self, claim_label: str | None) -> str:
        if claim_label:
            return (
                f"Puedo ayudarte con el siniestro {claim_label} en varios frentes:\n"
                "- Explicar por que fue priorizado.\n"
                "- Preparar un resumen ejecutivo.\n"
                "- Decirte que revisar primero.\n"
                "- Revisar documentos y soportes.\n"
                "- Aclarar score, nivel y accion sugerida."
            )
        return (
            "Puedo ayudarte a revisar riesgos de siniestros, patrones de alertas, proveedores, "
            "documentos con novedades, montos atipicos y casos que conviene priorizar."
        )

    def _out_of_scope_answer(self, normalized: str, claim_label: str | None) -> str:
        topic = self._out_of_scope_topic(normalized)
        if claim_label:
            return (
                f"Lo siento, no estoy apto para responder sobre {topic}. "
                "Mi funcion es apoyar la revision antifraude y la gestion de siniestros.\n\n"
                f"Puedo ayudarte con el siniestro {claim_label}: explicar alertas, revisar documentos, "
                "preparar un resumen ejecutivo o sugerir los proximos pasos."
            )
        return (
            f"Lo siento, no estoy apto para responder sobre {topic}. "
            "Mi funcion es apoyar analisis de riesgo en siniestros: alertas, proveedores, documentos, "
            "montos atipicos y priorizacion de casos."
        )

    def _out_of_scope_topic(self, normalized: str) -> str:
        if any(term in normalized for term in ("css", "html", "javascript", "div", "programacion", "codigo")):
            return "programacion o diseno web"
        if any(term in normalized for term in ("cuanto es", "suma de", "resta de", "multiplica", "divide", "calcula")):
            return "calculos generales"
        if any(term in normalized for term in ("clima", "deporte", "futbol", "pelicula", "restaurante", "viaje")):
            return "temas generales fuera del analisis de siniestros"
        return "esa pregunta fuera del contexto de siniestros"

    def _claim_overview_answer(self, claim: Claim) -> str:
        label = self._claim_label(claim)
        assessment = claim.risk_assessment
        if not assessment:
            return (
                f"Tengo el siniestro {label} en contexto, pero aun no tiene evaluacion de riesgo. "
                "Primero habria que recalcular o generar el score del caso."
            )

        alerts = self._top_alerts(claim)
        strongest_signal = alerts[0].title.lower() if alerts else "sin alertas principales"
        return (
            f"Tengo el siniestro {label} en contexto. Esta en nivel {assessment.level} "
            f"con score {assessment.score}/100. La senal mas fuerte por ahora es: "
            f"{strongest_signal}. Puedes pedirme los motivos, un resumen ejecutivo, "
            "documentos o que revisar primero."
        )

    def _claim_status_answer(self, claim: Claim) -> str:
        label = self._claim_label(claim)
        assessment = claim.risk_assessment
        if not assessment:
            return f"El siniestro {label} aun no tiene score calculado."

        return (
            f"El siniestro {label} esta en nivel {assessment.level} con score "
            f"{assessment.score}/100. La accion sugerida es: {assessment.suggested_action}."
        )

    def _claim_reasons_answer(self, db: Session, claim: Claim) -> str:
        label = self._claim_label(claim)
        assessment = claim.risk_assessment
        if not assessment:
            return f"No puedo explicar los motivos de {label} porque aun no tiene evaluacion de riesgo."

        alerts = self._top_alerts(claim)
        alert_text = "\n".join(
            self._format_alert_for_summary(db, alert, index)
            for index, alert in enumerate(alerts[:5], start=1)
        )
        return (
            f"{label} fue priorizado como {assessment.level} principalmente por estas senales:\n"
            f"{alert_text or '- No hay alertas relevantes registradas.'}\n\n"
            "En simple: no es una acusacion de fraude, pero si hay suficientes indicadores "
            "para revisarlo antes de continuar el flujo normal."
        )

    def _claim_next_steps_answer(self, claim: Claim) -> str:
        label = self._claim_label(claim)
        assessment = claim.risk_assessment
        if not assessment:
            return f"Para {label}, primero generaria el score de riesgo antes de definir acciones."

        alerts = self._top_alerts(claim)
        return (
            f"Para {label}, revisaria esto primero:\n"
            f"{self._recommended_steps(alerts)}\n\n"
            f"Accion sugerida del modelo: {assessment.suggested_action}."
        )

    def _claim_documents_answer(self, claim: Claim) -> str:
        label = self._claim_label(claim)
        if not claim.documents:
            return f"No tengo documentos registrados para el siniestro {label}."

        documents = sorted(
            claim.documents,
            key=lambda document: (document.status == "completo", document.document_type or document.id),
        )
        rows = []
        for document in documents[:12]:
            note = f" - {document.notes}" if document.notes else ""
            rows.append(f"- {document.document_type or 'Documento'}: {document.status}{note}")
        return f"Documentos del siniestro {label}:\n" + "\n".join(rows)

    def _top_alerts(self, claim: Claim, *, limit: int = 5) -> list[RiskAlert]:
        assessment = claim.risk_assessment
        if not assessment:
            return []
        return sorted(assessment.alerts, key=lambda alert: alert.points or 0, reverse=True)[:limit]

    def _explain_claim(self, db: Session, claim: Claim) -> str:
        if not claim.risk_assessment:
            return f"El siniestro {self._claim_label(claim)} aun no tiene evaluacion de riesgo."

        assessment = claim.risk_assessment
        top_alerts = self._top_alerts(claim)
        alert_text = "\n".join(
            self._format_alert_for_summary(db, alert, index)
            for index, alert in enumerate(top_alerts, start=1)
        )
        case_lines = [
            f"- Siniestro: {self._claim_label(claim)}",
            f"- Ramo/cobertura: {claim.branch or 'No informado'} / {claim.coverage or 'No informado'}",
            f"- Monto reclamado: {claim.claimed_amount or 'No informado'}",
        ]
        if claim.status:
            case_lines.append(f"- Estado operativo: {claim.status}")

        return (
            f"Resumen ejecutivo - {self._claim_label(claim)}\n\n"
            "Datos del caso\n"
            f"{chr(10).join(case_lines)}\n\n"
            "Estado de riesgo\n"
            f"- Score: {assessment.score}/100\n"
            f"- Nivel: {assessment.level}\n"
            f"- Accion sugerida: {assessment.suggested_action}\n\n"
            "Lectura ejecutiva\n"
            f"{self._executive_reading(assessment.level, top_alerts)}\n\n"
            "Hallazgos principales\n"
            f"{alert_text or '- Sin alertas relevantes.'}\n\n"
            "Siguientes pasos recomendados\n"
            f"{self._recommended_steps(top_alerts)}\n\n"
            "Nota\n"
            "Esta alerta no acusa fraude ni debe usarse como decision automatica; "
            "prioriza el caso para revision humana documentada."
        )

    def _format_alert_for_summary(self, db: Session, alert: RiskAlert, index: int) -> str:
        description = self._display_alert_description(db, alert.description or "Sin descripcion adicional.")
        return f"{index}. {alert.title} (+{alert.points or 0}): {description}"

    def _executive_reading(self, level: str | None, alerts: list[RiskAlert]) -> str:
        if not alerts:
            return "No se identifican alertas principales para priorizar este caso."

        signals = "; ".join(alert.title.lower() for alert in alerts[:3])
        if level == "rojo":
            return (
                "El caso debe priorizarse para revision especializada porque concentra "
                f"senales de alto impacto: {signals}."
            )
        if level == "amarillo":
            return (
                "El caso requiere revision documental antes de continuar el flujo normal "
                f"por estas senales: {signals}."
            )
        return (
            "El caso puede continuar con monitoreo, manteniendo trazabilidad sobre estas "
            f"senales: {signals}."
        )

    def _recommended_steps(self, alerts: list[RiskAlert]) -> str:
        codes = {alert.code for alert in alerts}
        steps: list[str] = []
        if "RF-04" in codes:
            steps.append("- Validar antecedentes, restricciones y soporte operativo del proveedor asociado.")
        if "RF-06" in codes:
            steps.append("- Comparar la narrativa y documentos contra el siniestro similar referenciado.")
        if "RF-03" in codes:
            steps.append("- Revisar recurrencia del asegurado, vehiculo o conductor antes de aprobar pagos.")
        if "RF-02" in codes:
            steps.append("- Confirmar fechas de ocurrencia, reporte y soportes de denuncia.")
        if "RF-05" in codes:
            steps.append("- Completar o corregir documentos faltantes, ilegibles o inconsistentes.")
        if "RF-07" in codes or "RF-09" in codes:
            steps.append("- Contrastar monto reclamado con cobertura, suma asegurada e historico comparable.")

        steps.append("- Registrar la decision final con evidencia de revision humana.")
        return "\n".join(steps[:4])

    def _display_alert_description(self, db: Session, description: str) -> str:
        display_description = description
        for claim_id in sorted(set(CLAIM_ID_PATTERN.findall(description))):
            display_description = display_description.replace(claim_id, self._claim_reference(db, claim_id))
        return display_description

    def _claim_reference(self, db: Session, claim_id: str) -> str:
        try:
            code = db.scalar(select(Claim.code).where(Claim.id == claim_id))
        except SQLAlchemyError:
            return "previo"
        return str(code) if code else "previo"

    def _claim_label_from_id(self, db: Session, claim_id: str | None) -> str | None:
        if not claim_id:
            return None
        try:
            code = db.scalar(select(Claim.code).where(Claim.id == claim_id))
        except SQLAlchemyError:
            return claim_id
        return str(code) if code else claim_id

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

    def _is_uuid(self, value: str) -> bool:
        try:
            UUID(value)
        except ValueError:
            return False
        return True

    def _clip(self, value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[: limit - 3].rstrip() + "..."
