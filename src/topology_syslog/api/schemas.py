"""FastAPI レスポンス用 Pydantic スキーマ。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident_id: str
    created_at: datetime
    root_cause_node: str
    primary_event: str
    secondary_nodes: list[str]
    raw_log_count: int
    raw_logs: list[str]
    status: str
    condition: str
    recurrence_count: int
    maintenance_plan_id: str | None = None
    last_fault_at: datetime | None = None
    last_recovery_at: datetime | None = None
    flap_count: int = 0
    recovery_evidence: list[str] = []


class IncidentListOut(BaseModel):
    incidents: list[IncidentOut]
    total: int


class UnknownEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    signature: str
    vendor: str | None = None
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int
    severity_counts: dict[str, int]
    nodes: list[str]
    representative_message: str
    representative_severity: int | None = None
    classification_candidate: str | None = None
    recommended_action: str | None = None


class UnknownEventListOut(BaseModel):
    events: list[UnknownEventOut]
    total: int


class RawLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    knowledge_status: str
    knowledge_id: str | None = None
    event_classification: str
    event_action: str | None = None
    classification_reasons: list[dict[str, object]]


class RawLogListOut(BaseModel):
    logs: list[RawLogOut]
    total: int


class KnowledgeRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    signature: str
    description: str | None = None
    vendor: str | None = None
    classification: str | None = None
    correlation_role: str | None = None
    severity_policy: dict[str, str]
    dedup_window_sec: int | None = None
    runbook: tuple[str, ...]
    status: str
    confidence: float | None = None
    priority: int


class KnowledgeRuleCreate(BaseModel):
    rule_id: str
    signature: str
    description: str | None = None
    vendor: str | None = None
    classification: str | None = None
    correlation_role: str | None = None
    severity_policy: dict[str, str] = {}
    dedup_window_sec: int | None = None
    runbook: list[str] = []
    confidence: float | None = None
    priority: int = 0


class SimilarKnowledgeOut(BaseModel):
    incidents: list[IncidentOut]
    source: str


class KnowledgeAuditOut(BaseModel):
    event_id: int
    occurred_at: datetime
    event_type: str
    rule_id: str | None = None
    rule_version: int | None = None
    actor: str | None = None
    signature: str | None = None
    details: dict
