from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EventClassification(StrEnum):
    UNKNOWN = "unknown"
    NOISE = "noise"
    RETAIN_ONLY = "retain-only"
    STATE_CHANGE = "state-change"
    FAULT_SIGNAL = "fault-signal"
    RECOVERY = "recovery"
    CONFIG_CHANGE = "config-change"
    SECURITY = "security"


class EventAction(StrEnum):
    RETAIN_ONLY = "retain_only"
    CORRELATE_ONLY = "correlate_only"
    CREATE_INCIDENT = "create_incident"
    UPDATE_INCIDENT = "update_incident"
    REVIEW = "review"
    SECURITY_NOTIFY = "security_notify"


class IncidentCondition(StrEnum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    FLAPPING = "FLAPPING"


@dataclass(frozen=True)
class ClassificationReason:
    source: str
    detail: str
    confidence: float | None = None


@dataclass(frozen=True)
class EventClassificationResult:
    classification: EventClassification = EventClassification.UNKNOWN
    action: EventAction | None = None
    reasons: tuple[ClassificationReason, ...] = ()


@dataclass
class SyslogMessage:
    received_at: datetime
    source_ip: str
    hostname: str
    facility: int
    severity: int  # 0=EMERGENCY … 7=DEBUG
    message: str
    event_type: str | None = None  # Cisco IOS "%FAC-SEV-MNEM" など
    is_recovery: bool = False      # リンクアップ等の復旧イベント
    vendor: str | None = None
    normalized_signature: str | None = None
    knowledge_status: str = "unknown"  # "known" | "unknown"
    knowledge_id: str | None = None
    recommended_action: str | None = None
    knowledge_confidence: float | None = None
    event_classification: EventClassification = EventClassification.UNKNOWN
    event_action: EventAction | None = None
    classification_reasons: list[ClassificationReason] = field(default_factory=list)


@dataclass
class UnknownEvent:
    signature: str
    vendor: str | None
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int = 1
    severity_counts: dict[str, int] = field(default_factory=dict)
    nodes: list[str] = field(default_factory=list)
    representative_message: str = ""
    representative_severity: int | None = None
    classification_candidate: str | None = None
    recommended_action: str | None = None


@dataclass
class RawLogRecord:
    log_id: int
    received_at: datetime
    source_ip: str
    hostname: str
    facility: int
    severity: int
    message: str
    vendor: str | None = None
    event_type: str | None = None
    normalized_signature: str | None = None
    knowledge_status: str = "unknown"
    knowledge_id: str | None = None
    event_classification: str = EventClassification.UNKNOWN.value
    event_action: str | None = None
    classification_reasons: list[dict[str, object]] = field(default_factory=list)


@dataclass
class Incident:
    incident_id: str          # INC-YYYYMMDD-NNN
    created_at: datetime
    root_cause_node: str
    primary_event: str
    secondary_nodes: list[str] = field(default_factory=list)
    raw_log_count: int = 0
    raw_logs: list[str] = field(default_factory=list)
    status: str = "OPEN"      # オペレーター管理のライフサイクル: "OPEN" | "CLOSED"
    condition: str = IncidentCondition.ACTIVE.value  # ネットワーク現在状況（自動更新）
    recurrence_count: int = 0  # 同一根本原因の過去インシデント件数（保存直前に設定）
    maintenance_plan_id: str | None = None  # メンテナンス計画によって自動クローズされた場合の計画 ID
    last_fault_at: datetime | None = None
    last_recovery_at: datetime | None = None
    flap_count: int = 0
    recovery_evidence: list[str] = field(default_factory=list)
