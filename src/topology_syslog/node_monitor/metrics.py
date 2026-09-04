"""依存を追加しない Prometheus 互換の node-monitor メトリクス。"""
from __future__ import annotations

from collections import Counter

from topology_syslog.node_monitor.models import NodeState


class NodeMonitorMetrics:
    def __init__(self) -> None:
        self._checks_total: Counter[str] = Counter()
        self._state_changes_total: Counter[str] = Counter()

    def record_check(self, state: NodeState, changed: bool) -> None:
        self._checks_total[state.value] += 1
        if changed:
            self._state_changes_total[state.value] += 1

    def render(self) -> str:
        lines = [
            "# HELP node_monitor_checks_total Completed node checks by resulting state.",
            "# TYPE node_monitor_checks_total counter",
        ]
        lines.extend(
            f'node_monitor_checks_total{{state="{state}"}} {count}'
            for state, count in sorted(self._checks_total.items())
        )
        lines.extend([
            "# HELP node_monitor_state_changes_total Node state transitions by new state.",
            "# TYPE node_monitor_state_changes_total counter",
        ])
        lines.extend(
            f'node_monitor_state_changes_total{{state="{state}"}} {count}'
            for state, count in sorted(self._state_changes_total.items())
        )
        return "\n".join(lines) + "\n"