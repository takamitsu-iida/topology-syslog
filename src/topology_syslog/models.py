from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
    condition: str = "ACTIVE"  # ネットワーク現在状況（自動更新）: "ACTIVE" | "RECOVERED" | "FLAPPING"
    recurrence_count: int = 0  # 同一根本原因の過去インシデント件数（保存直前に設定）
