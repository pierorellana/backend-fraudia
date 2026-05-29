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
from app.models.enums import LoadStatus
from app.models.enums import RiskLevel
from sqlalchemy import SmallInteger

UUIDString = UUID(as_uuid=False).with_variant(String(36), "sqlite")
JSONBType = JSON().with_variant(JSONB, "postgresql")


class User(Base):
    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column("id_usuario", UUIDString, primary_key=True)
    name: Mapped[str | None] = mapped_column("nombre", String(160), nullable=True)
    email: Mapped[str | None] = mapped_column("email", String(160), nullable=True)
    role: Mapped[str | None] = mapped_column("rol", String(60), nullable=True)
    active: Mapped[bool] = mapped_column("activo", Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)


class Insured(Base):
    __tablename__ = "asegurados"

    id: Mapped[str] = mapped_column("id_asegurado", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(40), nullable=True, unique=True, index=True)
    name: Mapped[str | None] = mapped_column("nombres_asegurado", String(160), nullable=True)
    segment: Mapped[str | None] = mapped_column("segmento", String(50), nullable=True)
    seniority_months: Mapped[int | None] = mapped_column("antiguedad_meses", Integer, nullable=True)
    seniority_years: Mapped[int | None] = mapped_column("antiguedad_anios", Integer, nullable=True)
    city: Mapped[str | None] = mapped_column("ciudad", String(100), nullable=True, index=True)
    policy_count: Mapped[int] = mapped_column("num_polizas", Integer, default=0, nullable=False)
    claims_12m: Mapped[int] = mapped_column("reclamos_12m", Integer, default=0, nullable=False)
    historical_claims_total: Mapped[int] = mapped_column("reclamos_historico_total", Integer, default=0, nullable=False)
    liability_claims_without_third_party: Mapped[int] = mapped_column(
        "reclamos_rc_sin_tercero",
        Integer,
        default=0,
        nullable=False,
    )
    current_delinquency: Mapped[bool] = mapped_column("mora_actual", Boolean, default=False, nullable=False)
    client_score: Mapped[Decimal | None] = mapped_column("score_cliente", Numeric(5, 2), nullable=True)
    historical_risk_profile: Mapped[str | None] = mapped_column("perfil_riesgo_historico", String(80), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    policies: Mapped[list[Policy]] = relationship(back_populates="insured")
    claims: Mapped[list[Claim]] = relationship(back_populates="insured")
    vehicles: Mapped[list[Vehicle]] = relationship(back_populates="insured")


class Policy(Base):
    __tablename__ = "polizas"

    id: Mapped[str] = mapped_column("id_poliza", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(40), nullable=True, unique=True, index=True)
    insured_id: Mapped[str] = mapped_column("id_asegurado", ForeignKey("asegurados.id_asegurado"), index=True)
    branch: Mapped[str | None] = mapped_column("ramo", String(50), nullable=True, index=True)
    start_date: Mapped[date | None] = mapped_column("fecha_inicio", Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column("fecha_fin", Date, nullable=True)
    premium_amount: Mapped[Decimal | None] = mapped_column("prima", Numeric(12, 2), nullable=True)
    insured_amount: Mapped[Decimal | None] = mapped_column("suma_asegurada", Numeric(14, 2), nullable=True)
    deductible: Mapped[Decimal | None] = mapped_column("deducible", Numeric(12, 2), nullable=True)
    sales_channel: Mapped[str | None] = mapped_column("canal_venta", String(50), nullable=True)
    city: Mapped[str | None] = mapped_column("ciudad", String(100), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column("estado_poliza", String(30), nullable=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    insured: Mapped[Insured] = relationship(back_populates="policies")
    vehicles: Mapped[list[Vehicle]] = relationship(back_populates="policy", cascade="all, delete-orphan")
    claims: Mapped[list[Claim]] = relationship(back_populates="policy")


class Provider(Base):
    __tablename__ = "proveedores"

    id: Mapped[str] = mapped_column("id_proveedor", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(40), nullable=True, unique=True, index=True)
    name: Mapped[str | None] = mapped_column("nombre", String(150), nullable=True, index=True)
    provider_type: Mapped[str | None] = mapped_column("tipo", String(50), nullable=True)
    city: Mapped[str | None] = mapped_column("ciudad", String(100), nullable=True, index=True)
    associated_claims: Mapped[int] = mapped_column("reclamos_asociados", Integer, default=0, nullable=False)
    average_amount: Mapped[Decimal | None] = mapped_column("monto_promedio", Numeric(14, 2), nullable=True)
    observed_cases_pct: Mapped[Decimal | None] = mapped_column("pct_casos_observados", Numeric(5, 2), nullable=True)
    seniority_months: Mapped[int | None] = mapped_column("antiguedad_meses", Integer, nullable=True)
    is_restricted: Mapped[bool] = mapped_column("en_lista_restrictiva", Boolean, default=False, nullable=False)
    restriction_reason: Mapped[str | None] = mapped_column("motivo_restriccion", Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    claims: Mapped[list[Claim]] = relationship(back_populates="provider")


class Vehicle(Base):
    __tablename__ = "vehiculos"

    id: Mapped[str] = mapped_column("id_vehiculo", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(40), nullable=True, unique=True, index=True)
    policy_id: Mapped[str] = mapped_column("id_poliza", ForeignKey("polizas.id_poliza"), index=True)
    insured_id: Mapped[str | None] = mapped_column("id_asegurado", ForeignKey("asegurados.id_asegurado"), nullable=True, index=True)
    plate: Mapped[str | None] = mapped_column("placa", String(20), nullable=True, index=True)
    chassis: Mapped[str | None] = mapped_column("chasis", String(50), nullable=True)
    engine: Mapped[str | None] = mapped_column("motor", String(50), nullable=True)
    brand: Mapped[str | None] = mapped_column("marca", String(50), nullable=True)
    model: Mapped[str | None] = mapped_column("modelo", String(50), nullable=True)
    year: Mapped[int | None] = mapped_column("anio", Integer, nullable=True)
    color: Mapped[str | None] = mapped_column("color", String(30), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    policy: Mapped[Policy] = relationship(back_populates="vehicles")
    insured: Mapped[Insured | None] = relationship(back_populates="vehicles")
    claims: Mapped[list[Claim]] = relationship(back_populates="vehicle")


class DatasetLoad(Base):
    __tablename__ = "cargas_dataset"

    id: Mapped[str] = mapped_column("id_carga", UUIDString, primary_key=True)
    user_id: Mapped[str | None] = mapped_column("id_usuario", UUIDString, nullable=True, index=True)
    filename: Mapped[str | None] = mapped_column("nombre_archivo", String(255), nullable=True)
    source_type: Mapped[str | None] = mapped_column("tipo_archivo", String(40), nullable=True)
    status: Mapped[str] = mapped_column("estado", String(20), default=LoadStatus.PENDING.value, nullable=False, index=True)
    total_rows: Mapped[int] = mapped_column("total_filas", Integer, default=0, nullable=False)
    valid_rows: Mapped[int] = mapped_column("filas_validas", Integer, default=0, nullable=False)
    invalid_rows: Mapped[int] = mapped_column("filas_invalidas", Integer, default=0, nullable=False)
    created_claims: Mapped[int] = mapped_column("siniestros_creados", Integer, default=0, nullable=False)
    created_policies: Mapped[int] = mapped_column("polizas_creadas", Integer, default=0, nullable=False)
    created_insured: Mapped[int] = mapped_column("asegurados_creados", Integer, default=0, nullable=False)
    created_providers: Mapped[int] = mapped_column("proveedores_creados", Integer, default=0, nullable=False)
    created_documents: Mapped[int] = mapped_column("documentos_creados", Integer, default=0, nullable=False)
    created_vehicles: Mapped[int] = mapped_column("vehiculos_creados", Integer, default=0, nullable=False)
    result_message: Mapped[str | None] = mapped_column("mensaje_resultado", Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column("iniciado_en", DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column("finalizado_en", DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    claims: Mapped[list[Claim]] = relationship(back_populates="import_batch")
    errors: Mapped[list[DatasetLoadError]] = relationship(
        back_populates="dataset_load",
        cascade="all, delete-orphan",
    )

    @property
    def summary(self) -> dict[str, int]:
        return {
            "created_claims": self.created_claims,
            "created_policies": self.created_policies,
            "created_insured": self.created_insured,
            "created_providers": self.created_providers,
            "created_documents": self.created_documents,
            "created_vehicles": self.created_vehicles,
            "errors": self.invalid_rows,
        }


class DatasetLoadError(Base):
    __tablename__ = "errores_carga"

    id: Mapped[str] = mapped_column("id_error", UUIDString, primary_key=True)
    import_id: Mapped[str] = mapped_column("id_carga", ForeignKey("cargas_dataset.id_carga"), index=True)
    sheet_name: Mapped[str | None] = mapped_column("hoja", String(80), nullable=True)
    row_number: Mapped[int | None] = mapped_column("fila", Integer, nullable=True)
    field_name: Mapped[str | None] = mapped_column("campo", String(120), nullable=True)
    received_value: Mapped[str | None] = mapped_column("valor_recibido", Text, nullable=True)
    message: Mapped[str] = mapped_column("mensaje", Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    dataset_load: Mapped[DatasetLoad] = relationship(back_populates="errors")

    @property
    def record_code(self) -> str | None:
        return self.received_value

    @property
    def raw_data(self) -> dict | None:
        return None


class Claim(Base):
    __tablename__ = "siniestros"

    id: Mapped[str] = mapped_column("id_siniestro", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(40), nullable=True, unique=True, index=True)
    import_id: Mapped[str | None] = mapped_column("id_carga", ForeignKey("cargas_dataset.id_carga"), nullable=True, index=True)
    policy_id: Mapped[str] = mapped_column("id_poliza", ForeignKey("polizas.id_poliza"), index=True)
    insured_id: Mapped[str] = mapped_column("id_asegurado", ForeignKey("asegurados.id_asegurado"), index=True)
    provider_id: Mapped[str | None] = mapped_column("id_proveedor", ForeignKey("proveedores.id_proveedor"), nullable=True, index=True)
    vehicle_id: Mapped[str | None] = mapped_column("id_vehiculo", ForeignKey("vehiculos.id_vehiculo"), nullable=True, index=True)
    branch: Mapped[str | None] = mapped_column("ramo", String(50), nullable=True, index=True)
    coverage: Mapped[str | None] = mapped_column("cobertura", String(120), nullable=True, index=True)
    occurrence_date: Mapped[date | None] = mapped_column("fecha_ocurrencia", Date, nullable=True, index=True)
    reported_date: Mapped[date | None] = mapped_column("fecha_reporte", Date, nullable=True)
    claimed_amount: Mapped[Decimal | None] = mapped_column("monto_reclamado", Numeric(14, 2), nullable=True)
    estimated_amount: Mapped[Decimal | None] = mapped_column("monto_estimado", Numeric(14, 2), nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column("monto_pagado", Numeric(14, 2), nullable=True)
    status: Mapped[str | None] = mapped_column("estado", String(50), nullable=True, index=True)
    flow_status: Mapped[str | None] = mapped_column("estado_flujo", String(60), nullable=True, index=True)
    latest_decision: Mapped[str | None] = mapped_column("ultima_decision", String(60), nullable=True)
    latest_reviewed_at: Mapped[datetime | None] = mapped_column("ultima_revision_en", DateTime, nullable=True)
    office: Mapped[str | None] = mapped_column("sucursal", String(100), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    documents_complete: Mapped[bool] = mapped_column("documentos_completos", Boolean, default=False, nullable=False)
    days_from_policy_start: Mapped[int | None] = mapped_column("dias_desde_inicio_poliza", Integer, nullable=True)
    days_from_policy_end: Mapped[int | None] = mapped_column("dias_desde_fin_poliza", Integer, nullable=True)
    report_delay_days: Mapped[int | None] = mapped_column("dias_entre_ocurrencia_reporte", Integer, nullable=True)
    insured_claim_history: Mapped[int] = mapped_column("historial_siniestros_asegurado", Integer, default=0, nullable=False)
    provider_list_restrictive: Mapped[bool] = mapped_column("proveedor_lista_restrictiva", Boolean, default=False, nullable=False)
    insured_amount: Mapped[Decimal | None] = mapped_column("suma_asegurada", Numeric(14, 2), nullable=True)
    ratio_to_insured_amount: Mapped[Decimal | None] = mapped_column("ratio_monto_suma_asegurada", Numeric(10, 6), nullable=True)
    max_narrative_similarity: Mapped[Decimal | None] = mapped_column("similitud_narrativa_max", Numeric(6, 4), nullable=True)
    police_report_number: Mapped[str | None] = mapped_column("numero_parte_policial", String(80), nullable=True)
    simulated_fraud_label: Mapped[int | None] = mapped_column(
    "etiqueta_fraude_simulada",SmallInteger,nullable=True,default=0,)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    import_batch: Mapped[DatasetLoad | None] = relationship(back_populates="claims")
    policy: Mapped[Policy] = relationship(back_populates="claims")
    insured: Mapped[Insured] = relationship(back_populates="claims")
    provider: Mapped[Provider | None] = relationship(back_populates="claims")
    vehicle: Mapped[Vehicle | None] = relationship(back_populates="claims")
    documents: Mapped[list[ClaimDocument]] = relationship(back_populates="claim", cascade="all, delete-orphan")
    risk_assessment: Mapped[RiskAssessment | None] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        uselist=False,
    )
    reviews: Mapped[list[ClaimReview]] = relationship(back_populates="claim", cascade="all, delete-orphan")

    @property
    def vehicle_plate(self) -> str | None:
        return self.vehicle.plate if self.vehicle else None


class ClaimDocument(Base):
    __tablename__ = "documentos"

    id: Mapped[str] = mapped_column("id_documento", UUIDString, primary_key=True)
    code: Mapped[str | None] = mapped_column("code", String(40), nullable=True, unique=True, index=True)
    claim_id: Mapped[str] = mapped_column("id_siniestro", ForeignKey("siniestros.id_siniestro"), index=True)
    document_type: Mapped[str | None] = mapped_column("tipo_documento", String(80), nullable=True)
    file_name: Mapped[str | None] = mapped_column("nombre_archivo_pdf", String(255), nullable=True)
    delivered: Mapped[bool] = mapped_column("entregado", Boolean, default=True, nullable=False)
    legible: Mapped[bool] = mapped_column("legible", Boolean, default=True, nullable=False)
    issue_date: Mapped[date | None] = mapped_column("fecha_emision", Date, nullable=True)
    inconsistency_detected: Mapped[bool] = mapped_column("inconsistencia_detectada", Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column("observacion", Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

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


class ScoringRule(Base):
    __tablename__ = "reglas_puntuacion"

    id: Mapped[int] = mapped_column("id_regla", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column("codigo_regla", String(20), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column("nombre", String(160), nullable=False)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    category: Mapped[str | None] = mapped_column("categoria", String(80), nullable=True)
    max_score: Mapped[int | None] = mapped_column("puntaje_maximo", Integer, nullable=True)
    rule_type: Mapped[str | None] = mapped_column("tipo_regla", String(60), nullable=True)
    active: Mapped[bool] = mapped_column("activa", Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    conditions: Mapped[list[RuleCondition]] = relationship(back_populates="rule", cascade="all, delete-orphan")


class RuleCondition(Base):
    __tablename__ = "condiciones_regla"

    id: Mapped[int] = mapped_column("id_condicion", Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column("id_regla", ForeignKey("reglas_puntuacion.id_regla"), index=True)
    name: Mapped[str | None] = mapped_column("nombre_condicion", String(160), nullable=True)
    field_name: Mapped[str | None] = mapped_column("campo_evaluado", String(120), nullable=True)
    operator: Mapped[str | None] = mapped_column("operador", String(20), nullable=True)
    value_min: Mapped[Decimal | None] = mapped_column("valor_min", Numeric(14, 4), nullable=True)
    value_max: Mapped[Decimal | None] = mapped_column("valor_max", Numeric(14, 4), nullable=True)
    value_text: Mapped[str | None] = mapped_column("valor_texto", String(255), nullable=True)
    points: Mapped[int | None] = mapped_column("puntaje", Integer, nullable=True)
    result_description: Mapped[str | None] = mapped_column("descripcion_resultado", Text, nullable=True)
    active: Mapped[bool] = mapped_column("activa", Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    rule: Mapped[ScoringRule] = relationship(back_populates="conditions")


class RiskAssessment(Base):
    __tablename__ = "scores_fraude"
    __table_args__ = (UniqueConstraint("id_siniestro", name="uq_scores_fraude_siniestro"),)

    id: Mapped[str] = mapped_column("id_score", UUIDString, primary_key=True)
    claim_id: Mapped[str] = mapped_column("id_siniestro", ForeignKey("siniestros.id_siniestro"), unique=True, index=True)
    score_rules: Mapped[Decimal | None] = mapped_column("score_reglas", Numeric(5, 2), nullable=True)
    score_ai_model: Mapped[Decimal | None] = mapped_column("score_modelo_ia", Numeric(5, 2), nullable=True)
    score_nlp: Mapped[Decimal | None] = mapped_column("score_nlp", Numeric(5, 2), nullable=True)
    score: Mapped[Decimal | None] = mapped_column("score_total", Numeric(5, 2), nullable=True, index=True)
    level: Mapped[str | None] = mapped_column("nivel_riesgo", String(20), nullable=True, index=True)
    calculated_at: Mapped[datetime | None] = mapped_column("calculado_en", DateTime, nullable=True)
    model_version: Mapped[str | None] = mapped_column("version_modelo", String(40), nullable=True)
    signal_detail: Mapped[dict | None] = mapped_column("detalle_señales", JSONBType, nullable=True)
    explanation: Mapped[str | None] = mapped_column("explicacion_generada", Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column("recomendacion", Text, nullable=True)
    reviewed_by_analyst: Mapped[bool] = mapped_column("revisado_por_analista", Boolean, default=False, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column("revisado_por", UUIDString, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column("revisado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    claim: Mapped[Claim] = relationship(back_populates="risk_assessment")
    alerts: Mapped[list[RiskAlert]] = relationship(back_populates="assessment", cascade="all, delete-orphan")

    @property
    def ethical_disclaimer(self) -> str:
        return (
            "Este resultado identifica posibles alertas y requiere revision humana; "
            "no constituye una acusacion ni una decision automatica."
        )

    @property
    def suggested_action(self) -> str:
        if self.recommendation:
            return self.recommendation
        if self.level == RiskLevel.HIGH.value:
            return "Escalar a revision especializada antifraude"
        if self.level == RiskLevel.MEDIUM.value:
            return "Solicitar revision documental reforzada"
        return "Continuar flujo normal con monitoreo"


class RiskAlert(Base):
    __tablename__ = "alertas"

    id: Mapped[str] = mapped_column("id_alerta", UUIDString, primary_key=True)
    claim_id: Mapped[str] = mapped_column("id_siniestro", ForeignKey("siniestros.id_siniestro"), index=True)
    assessment_id: Mapped[str] = mapped_column("id_score", ForeignKey("scores_fraude.id_score"), index=True)
    rule_id: Mapped[int | None] = mapped_column("id_regla", ForeignKey("reglas_puntuacion.id_regla"), nullable=True)
    condition_id: Mapped[int | None] = mapped_column("id_condicion", ForeignKey("condiciones_regla.id_condicion"), nullable=True)
    code: Mapped[str | None] = mapped_column("codigo_regla", String(20), nullable=True, index=True)
    rule_name: Mapped[str | None] = mapped_column("nombre_regla", String(180), nullable=True)
    category: Mapped[str | None] = mapped_column("categoria", String(80), nullable=True)
    severity: Mapped[str | None] = mapped_column("nivel", String(20), nullable=True, index=True)
    points: Mapped[int | None] = mapped_column("puntos", Integer, nullable=True)
    detected_value: Mapped[str | None] = mapped_column("valor_detectado", String(255), nullable=True)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column("recomendacion", Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column("generada_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)

    assessment: Mapped[RiskAssessment] = relationship(back_populates="alerts")
    rule: Mapped[ScoringRule | None] = relationship()
    condition: Mapped[RuleCondition | None] = relationship()

    @property
    def title(self) -> str:
        return self.rule_name or self.category or self.code or "Alerta de riesgo"


class ClaimDecisionCatalog(Base):
    __tablename__ = "catalogo_decisiones"

    id: Mapped[int] = mapped_column("id_decision", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column("codigo", String(60), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column("nombre", String(160), nullable=False)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    default_resulting_status: Mapped[str | None] = mapped_column("estado_resultante_default", String(60), nullable=True)
    requires_comment: Mapped[bool] = mapped_column("requiere_comentario", Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column("activa", Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)


class ClaimStatusCatalog(Base):
    __tablename__ = "catalogo_estados_siniestro"

    id: Mapped[int] = mapped_column("id_estado", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column("codigo", String(60), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column("nombre", String(160), nullable=False)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    is_final_status: Mapped[bool] = mapped_column("es_estado_final", Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column("activo", Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("actualizado_en", DateTime, nullable=True)


class ClaimReview(Base):
    __tablename__ = "revisiones_siniestro"

    id: Mapped[str] = mapped_column("id_revision", UUIDString, primary_key=True)
    claim_id: Mapped[str] = mapped_column("id_siniestro", ForeignKey("siniestros.id_siniestro"), index=True)
    user_id: Mapped[str | None] = mapped_column("id_usuario", UUIDString, nullable=True)
    decision_id: Mapped[int | None] = mapped_column("id_decision", ForeignKey("catalogo_decisiones.id_decision"), nullable=True)
    resulting_status_id: Mapped[int | None] = mapped_column(
        "id_estado_resultante",
        ForeignKey("catalogo_estados_siniestro.id_estado"),
        nullable=True,
    )
    decision_code: Mapped[str] = mapped_column("decision", String(60), nullable=False, index=True)
    resulting_status: Mapped[str] = mapped_column("estado_resultante", String(60), nullable=False, index=True)
    comment: Mapped[str | None] = mapped_column("comentario", Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column("revisado_en", DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    claim: Mapped[Claim] = relationship(back_populates="reviews")
    decision: Mapped[ClaimDecisionCatalog | None] = relationship()
    status_catalog: Mapped[ClaimStatusCatalog | None] = relationship()


class ChatSession(Base):
    __tablename__ = "sesiones_chat"

    id: Mapped[str] = mapped_column("id_sesion", UUIDString, primary_key=True)
    user_id: Mapped[str | None] = mapped_column("id_usuario", UUIDString, nullable=True)
    title: Mapped[str | None] = mapped_column("titulo", String(160), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creada_en", DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column("ultima_actividad", DateTime, nullable=True)
    active_filters: Mapped[dict | None] = mapped_column("filtros_activos", JSONBType, nullable=True)
    active: Mapped[bool] = mapped_column("activa", Boolean, default=True, nullable=False)

    messages: Mapped[list[ChatMessage]] = relationship(back_populates="session", cascade="all, delete-orphan")

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
            filters["claim_id"] = value
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
    context_data: Mapped[dict | None] = mapped_column("contexto_datos", JSONBType, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column("tokens_usados", Integer, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column("creado_en", DateTime, nullable=True)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
