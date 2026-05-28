from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata

from app.models.domain import Claim
from app.models.domain import ClaimDocument
from app.models.domain import Policy
from app.models.domain import Provider
from app.models.enums import AlertSeverity
from app.models.enums import RiskLevel


@dataclass(frozen=True)
class RuleAlert:
    code: str
    title: str
    description: str
    points: int
    severity: AlertSeverity


@dataclass(frozen=True)
class RiskContext:
    insured_claim_count: int
    vehicle_claim_count: int
    driver_claim_count: int
    provider_claim_count: int
    average_claimed_amount: Decimal | None
    peer_claim_count: int
    amount_z_score: float | None
    similar_claim_id: str | None
    narrative_similarity: float


@dataclass(frozen=True)
class RiskEvaluation:
    score: int
    level: RiskLevel
    suggested_action: str
    explanation: str
    alerts: list[RuleAlert]


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


SUSPICIOUS_DYNAMIC_TERMS = (
    "sin testigos",
    "noche",
    "madrugada",
    "llaves dentro",
    "conductor desconocido",
    "tercero no identificado",
    "version contradictoria",
    "estacionado",
)


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


def classify_score(score: int) -> RiskLevel:
    if score <= 40:
        return RiskLevel.LOW
    if score <= 75:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


def suggested_action(level: RiskLevel) -> str:
    if level == RiskLevel.HIGH:
        return "Escalar a revision especializada antifraude"
    if level == RiskLevel.MEDIUM:
        return "Escalar a revision documental"
    return "Continuar flujo normal con monitoreo"


class RiskEngine:
    def evaluate(self, claim: Claim, context: RiskContext) -> RiskEvaluation:
        alerts: list[RuleAlert] = []
        policy = claim.policy
        provider = claim.provider

        alerts.extend(self._policy_timing_alerts(claim, policy))
        alerts.extend(self._report_delay_alerts(claim))
        alerts.extend(self._frequency_alerts(context))
        alerts.extend(self._provider_alerts(provider, context))
        alerts.extend(self._document_alerts(claim.documents))
        alerts.extend(self._narrative_alerts(context))
        alerts.extend(self._amount_alerts(claim, policy, context))
        alerts.extend(self._anomaly_alerts(context))
        alerts.extend(self._dynamic_alerts(claim.description or ""))

        score = min(sum(alert.points for alert in alerts), 100)
        if any(alert.severity == AlertSeverity.CRITICAL for alert in alerts):
            score = max(score, 76)

        level = classify_score(score)
        explanation = self._build_explanation(score, level, alerts)

        return RiskEvaluation(
            score=score,
            level=level,
            suggested_action=suggested_action(level),
            explanation=explanation,
            alerts=alerts,
        )

    def _policy_timing_alerts(self, claim: Claim, policy: Policy) -> list[RuleAlert]:
        alerts: list[RuleAlert] = []
        if not claim.occurrence_date:
            return alerts

        days_from_start = claim.days_from_policy_start
        if days_from_start is None and policy.start_date:
            days_from_start = (claim.occurrence_date - policy.start_date).days

        days_to_end = claim.days_from_policy_end
        if days_to_end is None and policy.end_date:
            days_to_end = (policy.end_date - claim.occurrence_date).days

        if days_from_start is not None and days_from_start < 0:
            alerts.append(
                RuleAlert(
                    code="RF-01",
                    title="Siniestro antes del inicio de vigencia",
                    description=f"Ocurrio {abs(days_from_start)} dias antes del inicio de la poliza.",
                    points=30,
                    severity=AlertSeverity.CRITICAL,
                )
            )
            return alerts

        if days_to_end is not None and days_to_end < 0:
            alerts.append(
                RuleAlert(
                    code="RF-01",
                    title="Siniestro posterior al fin de vigencia",
                    description=f"Ocurrio {abs(days_to_end)} dias despues del fin de la poliza.",
                    points=30,
                    severity=AlertSeverity.CRITICAL,
                )
            )
            return alerts

        if days_from_start is not None and 0 <= days_from_start <= 7:
            alerts.append(
                RuleAlert(
                    code="RF-01",
                    title="Siniestro cerca del inicio de vigencia",
                    description=f"Ocurrio {days_from_start} dias despues del inicio de la poliza.",
                    points=18,
                    severity=AlertSeverity.HIGH,
                )
            )
        elif days_from_start is not None and 0 <= days_from_start <= 30:
            alerts.append(
                RuleAlert(
                    code="RF-01",
                    title="Siniestro en ventana temprana de poliza",
                    description=f"Ocurrio {days_from_start} dias despues del inicio de la poliza.",
                    points=8,
                    severity=AlertSeverity.MEDIUM,
                )
            )

        if days_to_end is not None and 0 <= days_to_end <= 7:
            alerts.append(
                RuleAlert(
                    code="RF-01",
                    title="Siniestro cerca del fin de vigencia",
                    description=f"Ocurrio {days_to_end} dias antes del fin de la poliza.",
                    points=14,
                    severity=AlertSeverity.HIGH,
                )
            )
        elif days_to_end is not None and 0 <= days_to_end <= 30:
            alerts.append(
                RuleAlert(
                    code="RF-01",
                    title="Siniestro en ventana final de poliza",
                    description=f"Ocurrio {days_to_end} dias antes del fin de la poliza.",
                    points=7,
                    severity=AlertSeverity.MEDIUM,
                )
            )

        return alerts

    def _anomaly_alerts(self, context: RiskContext) -> list[RuleAlert]:
        if context.amount_z_score is None or context.peer_claim_count < 5:
            return []

        if context.amount_z_score >= 3.5:
            return [
                RuleAlert(
                    code="RF-09",
                    title="Anomalia estadistica critica en monto",
                    description=(
                        "El monto reclamado esta muy por encima del comportamiento historico "
                        f"del ramo/cobertura (z-score {context.amount_z_score:.2f})."
                    ),
                    points=24,
                    severity=AlertSeverity.CRITICAL,
                )
            ]
        if context.amount_z_score >= 2.5:
            return [
                RuleAlert(
                    code="RF-09",
                    title="Anomalia estadistica en monto",
                    description=(
                        "El monto reclamado se aleja significativamente del comportamiento historico "
                        f"del ramo/cobertura (z-score {context.amount_z_score:.2f})."
                    ),
                    points=16,
                    severity=AlertSeverity.HIGH,
                )
            ]
        if context.amount_z_score >= 2.0:
            return [
                RuleAlert(
                    code="RF-09",
                    title="Monto inusual por modelo estadistico",
                    description=(
                        "El monto reclamado supera el umbral de anomalia moderada "
                        f"del ramo/cobertura (z-score {context.amount_z_score:.2f})."
                    ),
                    points=10,
                    severity=AlertSeverity.MEDIUM,
                )
            ]

        return []

    def _report_delay_alerts(self, claim: Claim) -> list[RuleAlert]:
        if not claim.occurrence_date or not claim.reported_date:
            return []

        delay = claim.report_delay_days
        if delay is None:
            delay = (claim.reported_date - claim.occurrence_date).days

        if delay <= 3:
            return []

        description = normalize_text(claim.description or "")
        is_theft = any(term in description for term in ("robo", "hurto", "sustraccion"))
        if is_theft and delay >= 5:
            return [
                RuleAlert(
                    code="RF-02",
                    title="Denuncia tardia en caso de robo",
                    description=f"El evento fue reportado {delay} dias despues de la ocurrencia.",
                    points=14,
                    severity=AlertSeverity.HIGH,
                )
            ]
        if delay >= 10:
            return [
                RuleAlert(
                    code="RF-02",
                    title="Reporte tardio del siniestro",
                    description=f"El evento fue reportado {delay} dias despues de la ocurrencia.",
                    points=12,
                    severity=AlertSeverity.HIGH,
                )
            ]
        return [
            RuleAlert(
                code="RF-02",
                title="Demora moderada en reporte",
                description=f"El evento fue reportado {delay} dias despues de la ocurrencia.",
                points=6,
                severity=AlertSeverity.MEDIUM,
            )
        ]

    def _frequency_alerts(self, context: RiskContext) -> list[RuleAlert]:
        alerts: list[RuleAlert] = []
        if context.insured_claim_count >= 4:
            alerts.append(
                RuleAlert(
                    code="RF-03",
                    title="Alta frecuencia de reclamos del asegurado",
                    description=f"El asegurado registra {context.insured_claim_count} siniestros.",
                    points=16,
                    severity=AlertSeverity.HIGH,
                )
            )
        elif context.insured_claim_count >= 3:
            alerts.append(
                RuleAlert(
                    code="RF-03",
                    title="Frecuencia inusual de reclamos del asegurado",
                    description=f"El asegurado registra {context.insured_claim_count} siniestros.",
                    points=10,
                    severity=AlertSeverity.MEDIUM,
                )
            )

        if context.vehicle_claim_count >= 3:
            alerts.append(
                RuleAlert(
                    code="RF-03",
                    title="Vehiculo con multiples reclamos",
                    description=f"El vehiculo registra {context.vehicle_claim_count} siniestros.",
                    points=14,
                    severity=AlertSeverity.HIGH,
                )
            )
        elif context.vehicle_claim_count >= 2:
            alerts.append(
                RuleAlert(
                    code="RF-03",
                    title="Vehiculo con reclamos repetidos",
                    description=f"El vehiculo registra {context.vehicle_claim_count} siniestros.",
                    points=8,
                    severity=AlertSeverity.MEDIUM,
                )
            )

        if context.driver_claim_count >= 3:
            alerts.append(
                RuleAlert(
                    code="RF-03",
                    title="Conductor con multiples reclamos",
                    description=f"El conductor registra {context.driver_claim_count} siniestros.",
                    points=12,
                    severity=AlertSeverity.HIGH,
                )
            )

        return alerts

    def _provider_alerts(self, provider: Provider | None, context: RiskContext) -> list[RuleAlert]:
        alerts: list[RuleAlert] = []
        if provider and provider.is_restricted:
            alerts.append(
                RuleAlert(
                    code="RF-04",
                    title="Proveedor en lista restrictiva",
                    description=f"El proveedor {provider.name or provider.id} esta marcado como restringido.",
                    points=35,
                    severity=AlertSeverity.CRITICAL,
                )
            )

        if context.provider_claim_count >= 4:
            alerts.append(
                RuleAlert(
                    code="RF-04",
                    title="Proveedor recurrente",
                    description=f"El proveedor aparece en {context.provider_claim_count} siniestros.",
                    points=12,
                    severity=AlertSeverity.MEDIUM,
                )
            )

        return alerts

    def _document_alerts(self, documents: list[ClaimDocument]) -> list[RuleAlert]:
        problematic = [
            document
            for document in documents
            if not document.delivered or not document.legible or document.inconsistency_detected
        ]
        if not problematic:
            return []

        points = min(8 * len(problematic), 24)
        has_inconsistency = any(document.inconsistency_detected for document in problematic)
        severity = AlertSeverity.HIGH if has_inconsistency else AlertSeverity.MEDIUM
        if has_inconsistency and len(problematic) >= 2:
            severity = AlertSeverity.CRITICAL
            points = max(points, 28)

        labels = ", ".join(f"{document.document_type or document.id}: {document.status}" for document in problematic)
        return [
            RuleAlert(
                code="RF-05",
                title="Documentos incompletos o inconsistentes",
                description=f"Se detectaron novedades documentales: {labels}.",
                points=points,
                severity=severity,
            )
        ]

    def _narrative_alerts(self, context: RiskContext) -> list[RuleAlert]:
        if not context.similar_claim_id:
            return []

        similarity_percent = round(context.narrative_similarity * 100)
        if context.narrative_similarity >= 0.85:
            return [
                RuleAlert(
                    code="RF-06",
                    title="Narrativa posiblemente clonada",
                    description=(
                        f"La descripcion es {similarity_percent}% similar al siniestro "
                        f"{context.similar_claim_id}."
                    ),
                    points=28,
                    severity=AlertSeverity.CRITICAL,
                )
            ]
        if context.narrative_similarity >= 0.65:
            return [
                RuleAlert(
                    code="RF-06",
                    title="Narrativa similar a reclamo previo",
                    description=(
                        f"La descripcion es {similarity_percent}% similar al siniestro "
                        f"{context.similar_claim_id}."
                    ),
                    points=14,
                    severity=AlertSeverity.HIGH,
                )
            ]
        return []

    def _amount_alerts(self, claim: Claim, policy: Policy, context: RiskContext) -> list[RuleAlert]:
        alerts: list[RuleAlert] = []
        claimed_amount = claim.claimed_amount or Decimal("0")
        insured_amount = policy.insured_amount or Decimal("0")
        if insured_amount > 0:
            ratio = claimed_amount / insured_amount
            if ratio >= Decimal("0.95"):
                alerts.append(
                    RuleAlert(
                        code="RF-07",
                        title="Monto cercano a la suma asegurada",
                        description=f"El monto reclamado representa {ratio:.0%} de la suma asegurada.",
                        points=18,
                        severity=AlertSeverity.HIGH,
                    )
                )
            elif ratio >= Decimal("0.80"):
                alerts.append(
                    RuleAlert(
                        code="RF-07",
                        title="Monto alto frente a suma asegurada",
                        description=f"El monto reclamado representa {ratio:.0%} de la suma asegurada.",
                        points=10,
                        severity=AlertSeverity.MEDIUM,
                    )
                )

        if context.average_claimed_amount and context.average_claimed_amount > 0:
            ratio_to_average = claimed_amount / context.average_claimed_amount
            if ratio_to_average >= Decimal("2.50"):
                alerts.append(
                    RuleAlert(
                        code="RF-07",
                        title="Monto atipico frente al promedio",
                        description=f"El monto es {ratio_to_average:.1f} veces el promedio del ramo/cobertura.",
                        points=14,
                        severity=AlertSeverity.HIGH,
                    )
                )

        return alerts

    def _dynamic_alerts(self, description: str) -> list[RuleAlert]:
        normalized = normalize_text(description)
        alerts: list[RuleAlert] = []

        if "perdida total" in normalized and any(term in normalized for term in ("robo", "hurto")):
            alerts.append(
                RuleAlert(
                    code="RF-08",
                    title="Perdida total por robo",
                    description="La descripcion combina perdida total con robo o hurto.",
                    points=20,
                    severity=AlertSeverity.CRITICAL,
                )
            )

        matched_terms = [term for term in SUSPICIOUS_DYNAMIC_TERMS if term in normalized]
        if len(matched_terms) >= 2:
            alerts.append(
                RuleAlert(
                    code="RF-08",
                    title="Dinamica del evento requiere revision",
                    description=f"Terminos detectados en la narrativa: {', '.join(matched_terms)}.",
                    points=10,
                    severity=AlertSeverity.MEDIUM,
                )
            )

        return alerts

    def _build_explanation(self, score: int, level: RiskLevel, alerts: list[RuleAlert]) -> str:
        if not alerts:
            return (
                f"Score {score}/100 ({level.value}). No se detectaron senales relevantes; "
                "el caso puede continuar el flujo normal."
            )

        top_alerts = sorted(alerts, key=lambda item: item.points, reverse=True)[:3]
        alert_text = "; ".join(f"{alert.title} (+{alert.points})" for alert in top_alerts)
        return (
            f"Score {score}/100 ({level.value}). El nivel se explica principalmente por: "
            f"{alert_text}. Esta salida prioriza revision humana y no constituye una acusacion."
        )
