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
    recurrence_count: int


class IncidentListOut(BaseModel):
    incidents: list[IncidentOut]
    total: int
