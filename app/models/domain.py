from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Numeric
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.enums import RiskLevel

UUIDString = UUID(as_uuid=False).with_variant(String(36), "sqlite")
JSONBType = JSON().with_variant(JSONB, "postgresql")


class Insured(Base):
    __tablename__ = "asegurados"

    id: Mapped[str] = mapped_column("id_asegurado", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(20), nullable=True, unique=True, index=True)
    segment: Mapped[str | None] = mapped_column("segmento", String(50), nullable=True)
    seniority_months: Mapped[int | None] = mapped_column("antiguedad_meses", Integer, nullable=True)
    city: Mapped[str | None] = mapped_column("ciudad", String(100), nullable=True)
    policy_count: Mapped[int] = mapped_column("num_polizas", Integer, default=0, nullable=False)
    claims_12m: Mapped[int] = mapped_column("reclamos_12m", Integer, default=0, nullable=False)
    current_delinquency: Mapped[bool] = mapped_column("mora_actual", Boolean, default=False, nullable=False)
    client_score: Mapped[Decimal | None] = mapped_column("score_cliente", Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    policies: Mapped[list[Policy]] = relationship(back_populates="insured")
    claims: Mapped[list[Claim]] = relationship(back_populates="insured")


class Policy(Base):
    __tablename__ = "polizas"

    id: Mapped[str] = mapped_column("id_poliza", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(20), nullable=True, unique=True, index=True)
    insured_id: Mapped[str] = mapped_column("id_asegurado", ForeignKey("asegurados.id_asegurado"), index=True)
    branch: Mapped[str] = mapped_column("ramo", String(50), index=True)
    start_date: Mapped[date] = mapped_column("fecha_inicio", Date, nullable=False)
    end_date: Mapped[date] = mapped_column("fecha_fin", Date, nullable=False)
    premium_amount: Mapped[Decimal | None] = mapped_column("prima", Numeric(12, 2), nullable=True)
    insured_amount: Mapped[Decimal | None] = mapped_column("suma_asegurada", Numeric(12, 2), nullable=True)
    deductible: Mapped[Decimal | None] = mapped_column("deducible", Numeric(12, 2), nullable=True)
    sales_channel: Mapped[str | None] = mapped_column("canal_venta", String(50), nullable=True)
    city: Mapped[str | None] = mapped_column("ciudad", String(100), nullable=True)
    status: Mapped[str | None] = mapped_column("estado_poliza", String(30), nullable=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    insured: Mapped[Insured] = relationship(back_populates="policies")
    vehicles: Mapped[list[Vehicle]] = relationship(back_populates="policy", cascade="all, delete-orphan")
    claims: Mapped[list[Claim]] = relationship(back_populates="policy")


class Provider(Base):
    __tablename__ = "proveedores"

    id: Mapped[str] = mapped_column("id_proveedor", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(20), nullable=True, unique=True, index=True)
    name: Mapped[str | None] = mapped_column("nombre", String(150), nullable=True, index=True)
    provider_type: Mapped[str | None] = mapped_column("tipo", String(50), nullable=True)
    city: Mapped[str | None] = mapped_column("ciudad", String(100), nullable=True)
    associated_claims: Mapped[int] = mapped_column("reclamos_asociados", Integer, default=0, nullable=False)
    average_amount: Mapped[Decimal | None] = mapped_column("monto_promedio", Numeric(12, 2), nullable=True)
    observed_cases_pct: Mapped[Decimal | None] = mapped_column("pct_casos_observados", Numeric(5, 2), nullable=True)
    seniority_months: Mapped[int | None] = mapped_column("antiguedad_meses", Integer, nullable=True)
    is_restricted: Mapped[bool] = mapped_column("en_lista_restrictiva", Boolean, default=False, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    claims: Mapped[list[Claim]] = relationship(back_populates="provider")


class Vehicle(Base):
    __tablename__ = "vehiculos"

    id: Mapped[str] = mapped_column("id_vehiculo", UUIDString, primary_key=True)
    policy_id: Mapped[str] = mapped_column("id_poliza", ForeignKey("polizas.id_poliza"), index=True)
    plate: Mapped[str | None] = mapped_column("placa", String(20), nullable=True, index=True)
    chassis: Mapped[str | None] = mapped_column("chasis", String(50), nullable=True)
    engine: Mapped[str | None] = mapped_column("motor", String(50), nullable=True)
    brand: Mapped[str | None] = mapped_column("marca", String(50), nullable=True)
    model: Mapped[str | None] = mapped_column("modelo", String(50), nullable=True)
    year: Mapped[int | None] = mapped_column("anio", Integer, nullable=True)
    color: Mapped[str | None] = mapped_column("color", String(30), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    policy: Mapped[Policy] = relationship(back_populates="vehicles")


class Claim(Base):
    __tablename__ = "siniestros"

    id: Mapped[str] = mapped_column("id_siniestro", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(20), nullable=True, unique=True, index=True)
    policy_id: Mapped[str] = mapped_column("id_poliza", ForeignKey("polizas.id_poliza"), index=True)
    insured_id: Mapped[str] = mapped_column("id_asegurado", ForeignKey("asegurados.id_asegurado"), index=True)
    provider_id: Mapped[str | None] = mapped_column(
        "id_proveedor",
        ForeignKey("proveedores.id_proveedor"),
        nullable=True,
        index=True,
    )
    branch: Mapped[str | None] = mapped_column("ramo", String(50), nullable=True, index=True)
    coverage: Mapped[str | None] = mapped_column("cobertura", String(80), nullable=True, index=True)
    occurrence_date: Mapped[date | None] = mapped_column("fecha_ocurrencia", Date, nullable=True, index=True)
    reported_date: Mapped[date | None] = mapped_column("fecha_reporte", Date, nullable=True)
    claimed_amount: Mapped[Decimal | None] = mapped_column("monto_reclamado", Numeric(12, 2), nullable=True)
    estimated_amount: Mapped[Decimal | None] = mapped_column("monto_estimado", Numeric(12, 2), nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column("monto_pagado", Numeric(12, 2), nullable=True)
    status: Mapped[str | None] = mapped_column("estado", String(50), nullable=True, index=True)
    office: Mapped[str | None] = mapped_column("sucursal", String(100), nullable=True)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    documents_complete: Mapped[bool] = mapped_column("documentos_completos", Boolean, default=False, nullable=False)
    days_from_policy_start: Mapped[int | None] = mapped_column("dias_desde_inicio_poliza", Integer, nullable=True)
    days_from_policy_end: Mapped[int | None] = mapped_column("dias_desde_fin_poliza", Integer, nullable=True)
    report_delay_days: Mapped[int | None] = mapped_column("dias_entre_ocurrencia_reporte", Integer, nullable=True)
    insured_claim_history: Mapped[int] = mapped_column(
        "historial_siniestros_asegurado",
        Integer,
        default=0,
        nullable=False,
    )
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    policy: Mapped[Policy] = relationship(back_populates="claims")
    insured: Mapped[Insured] = relationship(back_populates="claims")
    provider: Mapped[Provider | None] = relationship(back_populates="claims")
    documents: Mapped[list[ClaimDocument]] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
    )
    risk_assessment: Mapped[RiskAssessment | None] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def vehicle_plate(self) -> str | None:
        if self.policy and self.policy.vehicles:
            return self.policy.vehicles[0].plate
        return None


class ClaimDocument(Base):
    __tablename__ = "documentos"

    id: Mapped[str] = mapped_column("id_documento", UUIDString, primary_key=True)
    claim_id: Mapped[str] = mapped_column("id_siniestro", ForeignKey("siniestros.id_siniestro"), index=True)
    document_type: Mapped[str | None] = mapped_column("tipo_documento", String(80), nullable=True)
    delivered: Mapped[bool] = mapped_column("entregado", Boolean, default=False, nullable=False)
    legible: Mapped[bool] = mapped_column("legible", Boolean, default=True, nullable=False)
    issue_date: Mapped[date | None] = mapped_column("fecha_emision", Date, nullable=True)
    inconsistency_detected: Mapped[bool] = mapped_column(
        "inconsistencia_detectada",
        Boolean,
        default=False,
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column("observacion", Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    claim: Mapped[Claim] = relationship(back_populates="documents")

    @property
    def status(self) -> str:
        if self.inconsistency_detected:
            return "inconsistente"
        if not self.delivered:
            return "faltante"
        if not self.legible:
            return "ilegible"
        return "completo"


class RiskAssessment(Base):
    __tablename__ = "scores_fraude"
    __table_args__ = (UniqueConstraint("id_siniestro", name="uq_scores_fraude_siniestro"),)

    id: Mapped[str] = mapped_column("id_score", UUIDString, primary_key=True)
    claim_id: Mapped[str] = mapped_column("id_siniestro", ForeignKey("siniestros.id_siniestro"), unique=True, index=True)
    score: Mapped[Decimal | None] = mapped_column("score_total", Numeric(5, 2), nullable=True, index=True)
    level: Mapped[str | None] = mapped_column("nivel_riesgo", String(10), nullable=True, index=True)
    calculated_at: Mapped[datetime | None] = mapped_column("calculado_en", DateTime, nullable=True)
    model_version: Mapped[str | None] = mapped_column("version_modelo", String(30), default="rules-1.0", nullable=True)
    signal_detail: Mapped[dict | None] = mapped_column("detalle_señales", JSONBType, nullable=True)
    explanation: Mapped[str | None] = mapped_column("explicacion_generada", Text, nullable=True)
    reviewed_by_analyst: Mapped[bool] = mapped_column("revisado_por_analista", Boolean, default=False, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column("revisado_por", UUIDString, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column("revisado_en", DateTime, nullable=True)

    claim: Mapped[Claim] = relationship(back_populates="risk_assessment")
    alerts: Mapped[list[RiskAlert]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
    )

    @property
    def suggested_action(self) -> str:
        if self.level == RiskLevel.HIGH.value:
            return "Escalar a revision especializada antifraude"
        if self.level == RiskLevel.MEDIUM.value:
            return "Escalar a revision documental"
        return "Continuar flujo normal con monitoreo"


class RiskAlert(Base):
    __tablename__ = "alertas"

    id: Mapped[str] = mapped_column("id_alerta", UUIDString, primary_key=True)
    claim_id: Mapped[str] = mapped_column("id_siniestro", ForeignKey("siniestros.id_siniestro"), index=True)
    assessment_id: Mapped[str] = mapped_column("id_score", ForeignKey("scores_fraude.id_score"), index=True)
    code: Mapped[str | None] = mapped_column("codigo_regla", String(10), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column("categoria", String(80), nullable=True)
    severity: Mapped[str | None] = mapped_column("nivel", String(10), nullable=True, index=True)
    points: Mapped[int | None] = mapped_column("puntos", Integer, nullable=True)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column("recomendacion", Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column("generada_en", DateTime, nullable=True)

    assessment: Mapped[RiskAssessment] = relationship(back_populates="alerts")

    @property
    def title(self) -> str:
        return self.category or self.code or "Alerta de riesgo"


class ChatSession(Base):
    __tablename__ = "sesiones_chat"

    id: Mapped[str] = mapped_column("id_sesion", UUIDString, primary_key=True)
    user_id: Mapped[str | None] = mapped_column("id_usuario", UUIDString, nullable=True)
    title: Mapped[str | None] = mapped_column("titulo", String(160), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creada_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("ultima_actividad", DateTime, nullable=True)
    active_filters: Mapped[dict | None] = mapped_column("filtros_activos", JSONBType, nullable=True)
    active: Mapped[bool] = mapped_column("activa", Boolean, default=True, nullable=False)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )

    @property
    def claim_id(self) -> str | None:
        if not self.active_filters:
            return None
        return self.active_filters.get("id_siniestro") or self.active_filters.get("claim_id")

    @claim_id.setter
    def claim_id(self, value: str | None) -> None:
        filters = dict(self.active_filters or {})
        if value:
            filters["id_siniestro"] = value
        else:
            filters.pop("id_siniestro", None)
            filters.pop("claim_id", None)
        self.active_filters = filters or None


class ChatMessage(Base):
    __tablename__ = "mensajes_chat"

    id: Mapped[str] = mapped_column("id_mensaje", UUIDString, primary_key=True)
    session_id: Mapped[str] = mapped_column("id_sesion", ForeignKey("sesiones_chat.id_sesion"), index=True)
    role: Mapped[str] = mapped_column("rol", String(20), nullable=False)
    content: Mapped[str] = mapped_column("contenido", Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
