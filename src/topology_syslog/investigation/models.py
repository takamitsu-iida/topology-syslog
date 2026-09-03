"""調査機能のデータモデル。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CommandResult:
    device_id: str
    command: str
    output: str
    timestamp: datetime
    parsed: dict | None = None   # Genie パーサーが成功した場合の構造化データ
    error: str | None = None


@dataclass
class InvestigationReport:
    incident_id: str
    started_at: datetime
    status: str                                    # "running" | "completed" | "failed" | "interrupted"
    command_results: list[CommandResult] = field(default_factory=list)
    summary: str = ""
    completed_at: datetime | None = None
    error: str | None = None
