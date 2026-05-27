from enum import StrEnum


class AlertSeverity(StrEnum):
    LOW = "verde"
    MEDIUM = "amarillo"
    HIGH = "rojo"
    CRITICAL = "critico"


class RiskLevel(StrEnum):
    LOW = "verde"
    MEDIUM = "amarillo"
    HIGH = "rojo"
