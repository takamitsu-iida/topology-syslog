"""ノード状態モニターのデータモデル。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class NodeState(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProbeResult:
    probe_type: str
    target: str
    success: bool | None
    observed_at: datetime
    latency_ms: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class NodeStateRecord:
    node_id: str
    state: NodeState
    observed_at: datetime
    expires_at: datetime
    reason: str = ""
    probes: tuple[ProbeResult, ...] = field(default_factory=tuple)
    monitor_id: str | None = None


@dataclass(frozen=True)
class NodeStateChangeEvent:
    event_id: str
    event_type: str
    node_id: str
    previous_state: NodeState
    state: NodeState
    observed_at: datetime
    reason: str
    probes: tuple[ProbeResult, ...] = field(default_factory=tuple)