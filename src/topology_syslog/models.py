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


@dataclass
class Incident:
    incident_id: str          # INC-YYYYMMDD-NNN
    created_at: datetime
    root_cause_node: str
    primary_event: str
    secondary_nodes: list[str] = field(default_factory=list)
    raw_log_count: int = 0
    status: str = "OPEN"      # "OPEN" | "RESOLVED"
