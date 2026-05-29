from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata

from app.models.domain import Claim
from app.models.domain import ClaimDocument
from app.models.domain import Policy
from app.models.domain import Provider
from app.models.enums import RiskLevel


ETHICAL_DISCLAIMER = (
    "Este resultado identifica posibles alertas y requiere revision humana; "
    "no constituye una acusacion ni una decision automatica."
)

STOPWORDS = {
    "a",
    "al",
    "ante",
    "con",
    "de",
    "del",
    "el",
    "en",
    "la",
    "las",
    "lo",
    "los",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "un",
    "una",
    "y",
}


@dataclass(frozen=True)
class RuleDefinition:
    code: str
    name: str
    category: str
    description: str
    default_severity: str
    conditions: list[dict]


@dataclass(frozen=True)
class EvaluationAlert:
    code: str
    title: str
    rule_name: str
    category: str
    description: str
    points: int
    severity: str
    detected_value: str | None
    recommendation: str
    condition_code: str | None = None


@dataclass(frozen=True)
class RiskContext:
    narrative_similarity: float
    similar_claim_code: str | None
    ai_model_score: int = 0


@dataclass(frozen=True)
class RiskEvaluation:
    score_rules: int
    score_ai_model: int
    score_nlp: int
    score: int
    level: RiskLevel
    recommendation: str
    explanation: str
    ethical_disclaimer: str
    alerts: list[EvaluationAlert]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def tokenize(value: str) -> set[str]:
    normalized = normalize_text(value)
    tokens = set(re.findall(r"[a-z0-9]{3,}", normalized))
    return {token for token in tokens if token not in STOPWORDS}


def jaccard_similarity(left: str, right: str) -> float:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def rule_catalog() -> list[RuleDefinition]:
    return [
        RuleDefinition(
            code="RP-001",
            name="Reclamo cercano al borde de vigencia",
            category="Vigencia",
            description="Evalua cercania del evento al inicio o fin de la poliza.",
            default_severity="amarillo",
            conditions=[
                {"code": "RP-001-A", "description": "0 a 10 dias", "operator": "<=", "threshold_value": "10", "points": 8, "severity": "amarillo"},
                {"code": "RP-001-B", "description": "11 a 30 dias", "operator": "between", "threshold_value": "11-30", "points": 4, "severity": "verde"},
            ],
        ),
        RuleDefinition(
            code="RP-002",
            name="Reporte tardio",
            category="Temporalidad",
            description="Evalua dias transcurridos entre ocurrencia y reporte.",
            default_severity="amarillo",
            conditions=[
                {"code": "RP-002-A", "description": "Mayor a 7 dias", "operator": ">", "threshold_value": "7", "points": 5, "severity": "amarillo"},
                {"code": "RP-002-B", "description": "Entre 4 y 7 dias", "operator": "between", "threshold_value": "4-7", "points": 3, "severity": "verde"},
            ],
        ),
        RuleDefinition(
            code="RP-003",
            name="Alta frecuencia asegurado",
            category="Comportamiento",
            description="Evalua historial previo del asegurado.",
            default_severity="amarillo",
            conditions=[
                {"code": "RP-003-A", "description": "3 o mas reclamos", "operator": ">=", "threshold_value": "3", "points": 8, "severity": "amarillo"},
                {"code": "RP-003-B", "description": "2 reclamos", "operator": "=", "threshold_value": "2", "points": 4, "severity": "verde"},
            ],
        ),
        RuleDefinition(
            code="RP-004",
            name="Proveedor recurrente o restrictivo",
            category="Proveedor",
            description="Evalua recurrencia o inclusion en lista restrictiva.",
            default_severity="rojo",
            conditions=[
                {"code": "RP-004-A", "description": "Proveedor en lista restrictiva", "operator": "=", "threshold_value": "true", "points": 10, "severity": "critico"},
                {"code": "RP-004-B", "description": "Proveedor con mas de 2 reclamos asociados", "operator": ">", "threshold_value": "2", "points": 5, "severity": "amarillo"},
            ],
        ),
        RuleDefinition(
            code="RP-005",
            name="Documentos incompletos",
            category="Documentacion",
            description="Evalua si faltan documentos del expediente.",
            default_severity="amarillo",
            conditions=[
                {"code": "RP-005-A", "description": "Documentacion incompleta", "operator": "=", "threshold_value": "false", "points": 4, "severity": "amarillo"},
            ],
        ),
        RuleDefinition(
            code="RP-006",
            name="Narrativa similar",
            category="NLP",
            description="Evalua similitud de narrativas contra otros siniestros.",
            default_severity="amarillo",
            conditions=[
                {"code": "RP-006-A", "description": "Similitud >= 0.85", "operator": ">=", "threshold_value": "0.85", "points": 8, "severity": "amarillo"},
                {"code": "RP-006-B", "description": "Similitud 0.70 a 0.84", "operator": "between", "threshold_value": "0.70-0.84", "points": 4, "severity": "verde"},
            ],
        ),
        RuleDefinition(
            code="RP-007",
            name="Monto cercano a suma asegurada",
            category="Monto",
            description="Evalua cercania entre monto reclamado y suma asegurada.",
            default_severity="amarillo",
            conditions=[
                {"code": "RP-007-A", "description": "Ratio >= 0.95", "operator": ">=", "threshold_value": "0.95", "points": 5, "severity": "amarillo"},
            ],
        ),
        RuleDefinition(
            code="RP-008",
            name="Documentos inconsistentes",
            category="Documentacion",
            description="Evalua inconsistencias o ilegibilidad grave en documentos.",
            default_severity="rojo",
            conditions=[
                {"code": "RP-008-A", "description": "Documento inconsistente o ilegible", "operator": "=", "threshold_value": "true", "points": 10, "severity": "critico"},
            ],
        ),
        RuleDefinition(
            code="RP-009",
            name="Cobertura critica por perdida total y robo",
            category="Cobertura",
            description="Evalua combinacion de perdida total con robo o PTxRB.",
            default_severity="rojo",
            conditions=[
                {"code": "RP-009-A", "description": "Cobertura critica", "operator": "contains", "threshold_value": "PTxRB", "points": 10, "severity": "critico"},
            ],
        ),
    ]


def classify_score(score: int) -> RiskLevel:
    if score <= 40:
        return RiskLevel.LOW
    if score <= 75:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


def recommendation_for_level(level: RiskLevel) -> str:
    if level == RiskLevel.HIGH:
        return "Escalar a revision especializada antifraude antes de continuar el flujo."
    if level == RiskLevel.MEDIUM:
        return "Solicitar revision humana prioritaria con foco en documentos y consistencia del caso."
    return "Continuar el flujo normal con monitoreo y validaciones rutinarias."


class RiskEngine:
    def __init__(self) -> None:
        self.rule_map = {rule.code: rule for rule in rule_catalog()}

    def evaluate(self, claim: Claim, context: RiskContext) -> RiskEvaluation:
        alerts: list[EvaluationAlert] = []
        critical_red = False
        critical_yellow = False
        policy = claim.policy
        provider = claim.provider

        border_alert, border_yellow = self._policy_timing_alert(claim, policy)
        if border_alert:
            alerts.append(border_alert)
        critical_yellow = critical_yellow or border_yellow

        report_alert = self._report_delay_alert(claim)
        if report_alert:
            alerts.append(report_alert)

        frequency_alert = self._frequency_alert(claim)
        if frequency_alert:
            alerts.append(frequency_alert)

        provider_alert, provider_red = self._provider_alert(claim, provider)
        if provider_alert:
            alerts.append(provider_alert)
        critical_red = critical_red or provider_red

        documents_incomplete_alert = self._documents_incomplete_alert(claim)
        if documents_incomplete_alert:
            alerts.append(documents_incomplete_alert)

        nlp_alert, score_nlp, narrative_yellow = self._narrative_alert(context)
        if nlp_alert:
            alerts.append(nlp_alert)
        critical_yellow = critical_yellow or narrative_yellow

        amount_alert = self._insured_amount_alert(claim, policy)
        if amount_alert:
            alerts.append(amount_alert)

        inconsistent_documents_alert, documents_red = self._documents_inconsistent_alert(claim.documents)
        if inconsistent_documents_alert:
            alerts.append(inconsistent_documents_alert)
        critical_red = critical_red or documents_red

        coverage_alert, coverage_red = self._critical_coverage_alert(claim.coverage)
        if coverage_alert:
            alerts.append(coverage_alert)
        critical_red = critical_red or coverage_red

        score_ai_model = max(context.ai_model_score, 0)
        score_rules = sum(alert.points for alert in alerts if alert.code != "RP-006")
        score = min(100, score_rules + score_ai_model + score_nlp)
        if critical_red:
            score = max(score, 85)
        elif critical_yellow:
            score = max(score, 60)

        level = classify_score(score)
        if critical_red:
            level = RiskLevel.HIGH
        elif critical_yellow and level == RiskLevel.LOW:
            level = RiskLevel.MEDIUM

        recommendation = recommendation_for_level(level)
        explanation = self._build_explanation(level, alerts, context, recommendation)

        return RiskEvaluation(
            score_rules=score_rules,
            score_ai_model=score_ai_model,
            score_nlp=score_nlp,
            score=score,
            level=level,
            recommendation=recommendation,
            explanation=explanation,
            ethical_disclaimer=ETHICAL_DISCLAIMER,
            alerts=[
                EvaluationAlert(
                    code=alert.code,
                    title=alert.title,
                    rule_name=alert.rule_name,
                    category=alert.category,
                    description=alert.description,
                    points=alert.points,
                    severity=alert.severity,
                    detected_value=alert.detected_value,
                    recommendation=recommendation,
                    condition_code=alert.condition_code,
                )
                for alert in alerts
            ],
        )

    def _policy_timing_alert(self, claim: Claim, policy: Policy | None) -> tuple[EvaluationAlert | None, bool]:
        start_days = claim.days_from_policy_start
        end_days = claim.days_from_policy_end
        if claim.occurrence_date and policy:
            if start_days is None and policy.start_date:
                start_days = (claim.occurrence_date - policy.start_date).days
            if end_days is None and policy.end_date:
                end_days = (policy.end_date - claim.occurrence_date).days

        best_points = 0
        best_text: str | None = None
        if start_days is not None:
            if 0 <= start_days <= 10:
                best_points = 8
                best_text = f"{start_days} dias desde el inicio de la poliza"
            elif 11 <= start_days <= 30:
                best_points = 4
                best_text = f"{start_days} dias desde el inicio de la poliza"

        if end_days is not None:
            if 0 <= end_days <= 10 and 8 >= best_points:
                best_points = 8
                best_text = f"{end_days} dias para el fin de la poliza"
            elif 11 <= end_days <= 30 and 4 > best_points:
                best_points = 4
                best_text = f"{end_days} dias para el fin de la poliza"

        critical_yellow = any(
            value is not None and 0 <= value < 2
            for value in (start_days, end_days)
        )
        if best_points == 0 or not best_text:
            return None, critical_yellow

        condition_code = "RP-001-A" if best_points == 8 else "RP-001-B"
        return (
            EvaluationAlert(
                code="RP-001",
                title="Reclamo cercano al borde de vigencia",
                rule_name="Reclamo cercano al borde de vigencia",
                category="Vigencia",
                description=f"El siniestro se ubica en una ventana cercana a vigencia: {best_text}.",
                points=best_points,
                severity="amarillo" if best_points == 8 else "verde",
                detected_value=best_text,
                recommendation="",
                condition_code=condition_code,
            ),
            critical_yellow,
        )

    def _report_delay_alert(self, claim: Claim) -> EvaluationAlert | None:
        delay = claim.report_delay_days
        if delay is None and claim.occurrence_date and claim.reported_date:
            delay = (claim.reported_date - claim.occurrence_date).days
        if delay is None or delay <= 3:
            return None
        if delay > 7:
            points = 5
            condition_code = "RP-002-A"
            severity = "amarillo"
        else:
            points = 3
            condition_code = "RP-002-B"
            severity = "verde"
        return EvaluationAlert(
            code="RP-002",
            title="Reporte tardio",
            rule_name="Reporte tardio",
            category="Temporalidad",
            description=f"El siniestro fue reportado {delay} dias despues de la ocurrencia.",
            points=points,
            severity=severity,
            detected_value=str(delay),
            recommendation="",
            condition_code=condition_code,
        )

    def _frequency_alert(self, claim: Claim) -> EvaluationAlert | None:
        history = int(claim.insured_claim_history or 0)
        if history >= 3:
            points = 8
            severity = "amarillo"
            condition_code = "RP-003-A"
        elif history == 2:
            points = 4
            severity = "verde"
            condition_code = "RP-003-B"
        else:
            return None
        return EvaluationAlert(
            code="RP-003",
            title="Alta frecuencia asegurado",
            rule_name="Alta frecuencia asegurado",
            category="Comportamiento",
            description=f"El asegurado registra {history} reclamos previos asociados al caso.",
            points=points,
            severity=severity,
            detected_value=str(history),
            recommendation="",
            condition_code=condition_code,
        )

    def _provider_alert(self, claim: Claim, provider: Provider | None) -> tuple[EvaluationAlert | None, bool]:
        is_restricted = bool(claim.provider_list_restrictive or (provider and provider.is_restricted))
        if is_restricted:
            detected = provider.name if provider and provider.name else "Proveedor en lista restrictiva"
            return (
                EvaluationAlert(
                    code="RP-004",
                    title="Proveedor restringido",
                    rule_name="Proveedor recurrente o restrictivo",
                    category="Proveedor",
                    description="El proveedor asociado aparece en lista restrictiva y requiere revision especializada.",
                    points=10,
                    severity="critico",
                    detected_value=detected,
                    recommendation="",
                    condition_code="RP-004-A",
                ),
                True,
            )

        associated_claims = int(provider.associated_claims or 0) if provider else 0
        if associated_claims > 2:
            return (
                EvaluationAlert(
                    code="RP-004",
                    title="Proveedor recurrente",
                    rule_name="Proveedor recurrente o restrictivo",
                    category="Proveedor",
                    description=f"El proveedor registra {associated_claims} reclamos asociados y amerita contraste adicional.",
                    points=5,
                    severity="amarillo",
                    detected_value=str(associated_claims),
                    recommendation="",
                    condition_code="RP-004-B",
                ),
                False,
            )
        return None, False

    def _documents_incomplete_alert(self, claim: Claim) -> EvaluationAlert | None:
        if claim.documents_complete:
            return None
        return EvaluationAlert(
            code="RP-005",
            title="Documentos incompletos",
            rule_name="Documentos incompletos",
            category="Documentacion",
            description="El expediente presenta documentos faltantes o pendientes de completitud.",
            points=4,
            severity="amarillo",
            detected_value="false",
            recommendation="",
            condition_code="RP-005-A",
        )

    def _narrative_alert(self, context: RiskContext) -> tuple[EvaluationAlert | None, int, bool]:
        similarity = float(context.narrative_similarity or 0)
        if similarity >= 0.85:
            similar_text = (
                f" frente al siniestro {context.similar_claim_code}"
                if context.similar_claim_code
                else ""
            )
            return (
                EvaluationAlert(
                    code="RP-006",
                    title="Narrativa similar",
                    rule_name="Narrativa similar",
                    category="NLP",
                    description=f"La narrativa presenta una similitud de {similarity:.2f}{similar_text}.",
                    points=8,
                    severity="amarillo",
                    detected_value=f"{similarity:.2f}",
                    recommendation="",
                    condition_code="RP-006-A",
                ),
                8,
                similarity >= 0.95,
            )
        if similarity >= 0.70:
            return (
                EvaluationAlert(
                    code="RP-006",
                    title="Narrativa parcialmente similar",
                    rule_name="Narrativa similar",
                    category="NLP",
                    description=f"La narrativa presenta una similitud de {similarity:.2f} con otros casos comparables.",
                    points=4,
                    severity="verde",
                    detected_value=f"{similarity:.2f}",
                    recommendation="",
                    condition_code="RP-006-B",
                ),
                4,
                False,
            )
        return None, 0, False

    def _insured_amount_alert(self, claim: Claim, policy: Policy | None) -> EvaluationAlert | None:
        insured_amount = claim.insured_amount or (policy.insured_amount if policy else None)
        if not insured_amount or not claim.claimed_amount:
            return None
        insured_decimal = Decimal(insured_amount)
        if insured_decimal <= 0:
            return None
        ratio = Decimal(claim.claimed_amount) / insured_decimal
        if ratio < Decimal("0.95"):
            return None
        return EvaluationAlert(
            code="RP-007",
            title="Monto cercano a suma asegurada",
            rule_name="Monto cercano a suma asegurada",
            category="Monto",
            description=f"El monto reclamado representa {ratio:.0%} de la suma asegurada disponible.",
            points=5,
            severity="amarillo",
            detected_value=f"{ratio:.4f}",
            recommendation="",
            condition_code="RP-007-A",
        )

    def _documents_inconsistent_alert(self, documents: list[ClaimDocument]) -> tuple[EvaluationAlert | None, bool]:
        problematic = [document for document in documents if document.inconsistency_detected or not document.legible]
        if not problematic:
            return None, False
        labels = ", ".join(document.document_type or document.code or document.id for document in problematic)
        return (
            EvaluationAlert(
                code="RP-008",
                title="Documentos inconsistentes",
                rule_name="Documentos inconsistentes",
                category="Documentacion",
                description=f"Se detectaron documentos inconsistentes o ilegibles: {labels}.",
                points=10,
                severity="critico",
                detected_value=labels,
                recommendation="",
                condition_code="RP-008-A",
            ),
            True,
        )

    def _critical_coverage_alert(self, coverage: str | None) -> tuple[EvaluationAlert | None, bool]:
        normalized = normalize_text(coverage or "")
        is_critical = (
            "ptxrb" in normalized
            or ("perdida total" in normalized and ("robo" in normalized or "hurto" in normalized))
        )
        if not is_critical:
            return None, False
        return (
            EvaluationAlert(
                code="RP-009",
                title="Cobertura critica por perdida total y robo",
                rule_name="Cobertura critica por perdida total y robo",
                category="Cobertura",
                description="La cobertura declarada combina perdida total con robo y requiere revision especializada.",
                points=10,
                severity="critico",
                detected_value=coverage,
                recommendation="",
                condition_code="RP-009-A",
            ),
            True,
        )

    def _build_explanation(
        self,
        level: RiskLevel,
        alerts: list[EvaluationAlert],
        context: RiskContext,
        recommendation: str,
    ) -> str:
        if not alerts:
            return (
                f"El siniestro fue clasificado como {level.value} porque no activo alertas relevantes "
                "segun las reglas del MVP. Se recomienda mantener revision operativa normal. "
                f"{ETHICAL_DISCLAIMER}"
            )

        ordered = sorted(alerts, key=lambda item: item.points, reverse=True)
        drivers = "; ".join(
            f"{alert.title} (+{alert.points})"
            for alert in ordered[:4]
        )
        similarity_text = ""
        if context.narrative_similarity >= 0.70:
            similarity_text = f" La similitud narrativa observada fue {context.narrative_similarity:.2f}."
        return (
            f"El siniestro fue clasificado como {level.value} porque activo las siguientes alertas: "
            f"{drivers}.{similarity_text} Recomendacion: {recommendation} {ETHICAL_DISCLAIMER}"
        )
