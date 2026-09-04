"""TTL 付きノード状態ストア。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from topology_syslog.node_monitor.models import NodeState, NodeStateRecord


class NodeStateReader(Protocol):
    def get(self, node_id: str, *, now: datetime | None = None) -> NodeStateRecord:
        """ノードの現在状態を返す。未保存または期限切れは UNKNOWN とする。"""

    def get_many(
        self,
        node_ids: list[str],
        *,
        now: datetime | None = None,
    ) -> list[NodeStateRecord]:
        """指定ノードの現在状態を返す。"""


class InMemoryNodeStateStore:
    def __init__(self) -> None:
        self._records: dict[str, NodeStateRecord] = {}

    def put(self, record: NodeStateRecord) -> None:
        self._records[record.node_id] = record

    def get(self, node_id: str, *, now: datetime | None = None) -> NodeStateRecord:
        observed_at = now or datetime.now(tz=timezone.utc)
        record = self._records.get(node_id)
        if record is None:
            return _unknown(node_id, observed_at, "No state has been observed.")
        if observed_at >= record.expires_at:
            return _unknown(node_id, observed_at, "The last observed state has expired.")
        return record

    def get_many(
        self,
        node_ids: list[str],
        *,
        now: datetime | None = None,
    ) -> list[NodeStateRecord]:
        return [self.get(node_id, now=now) for node_id in node_ids]


def _unknown(node_id: str, observed_at: datetime, reason: str) -> NodeStateRecord:
    return NodeStateRecord(
        node_id=node_id,
        state=NodeState.UNKNOWN,
        observed_at=observed_at,
        expires_at=observed_at,
        reason=reason,
    )