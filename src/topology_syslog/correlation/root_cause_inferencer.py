"""根本原因推論エンジン。

F-3.3 仕様に基づき、ウィンドウ内の SyslogMessage 群から
Incident リストを生成する。
"""
from __future__ import annotations

from datetime import datetime, timezone

from topology_syslog.models import Incident, SyslogMessage
from topology_syslog.topology.graph_engine import GraphEngine


class RootCauseInferencer:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def infer(
        self,
        messages: list[SyslogMessage],
        graph: GraphEngine,
    ) -> list[Incident]:
        logged_nodes = {m.hostname for m in messages if graph.node_exists(m.hostname)}
        if not logged_nodes:
            return []

        now = datetime.now(tz=timezone.utc)
        date_str = now.strftime("%Y%m%d")
        incidents: list[Incident] = []
        assigned: set[str] = set()

        # 上流ノードがログを出していない = 根本原因候補
        root_causes = [
            n for n in logged_nodes
            if not graph.get_ancestors(n).intersection(logged_nodes)
        ]

        for rc in root_causes:
            descendants = graph.get_descendants(rc)
            secondary = sorted(logged_nodes.intersection(descendants))
            related = {rc, *secondary}
            related_msgs = [m for m in messages if m.hostname in related]
            primary_msg = next(
                (m.message for m in related_msgs if m.hostname == rc), "N/A"
            )
            incidents.append(Incident(
                incident_id=self._new_id(date_str),
                created_at=now,
                root_cause_node=rc,
                primary_event=primary_msg,
                secondary_nodes=secondary,
                raw_log_count=len(related_msgs),
                raw_logs=[m.message for m in related_msgs],
                status="OPEN",
            ))
            assigned.add(rc)
            assigned.update(secondary)

        # 根本原因グループに属さない独立ノード
        for node in sorted(logged_nodes - assigned):
            node_msgs = [m for m in messages if m.hostname == node]
            primary_msg = node_msgs[0].message if node_msgs else "N/A"
            incidents.append(Incident(
                incident_id=self._new_id(date_str),
                created_at=now,
                root_cause_node=node,
                primary_event=primary_msg,
                secondary_nodes=[],
                raw_log_count=len(node_msgs),
                raw_logs=[m.message for m in node_msgs],
                status="OPEN",
            ))

        return incidents

    def _new_id(self, date_str: str) -> str:
        n = self._counters.get(date_str, 0) + 1
        self._counters[date_str] = n
        return f"INC-{date_str}-{n:03d}"
