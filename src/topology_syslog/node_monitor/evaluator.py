"""プローブ結果からノード状態を判定する。"""
from __future__ import annotations

from topology_syslog.node_monitor.models import NodeState, ProbeResult


def evaluate_state(
    probes: tuple[ProbeResult, ...],
    *,
    required_probe_types: frozenset[str] = frozenset(),
) -> tuple[NodeState, str]:
    """複数の観測結果を安全側に倒して状態と理由へ変換する。"""
    successful_types = {probe.probe_type for probe in probes if probe.success is True}
    failed_types = {probe.probe_type for probe in probes if probe.success is False}

    if successful_types:
        missing_required = required_probe_types.intersection(failed_types)
        if missing_required:
            return NodeState.DEGRADED, f"Required probes failed: {', '.join(sorted(missing_required))}."
        return NodeState.UP, f"Successful probes: {', '.join(sorted(successful_types))}."
    if len(failed_types) >= 2:
        return NodeState.DOWN, f"Independent probes failed: {', '.join(sorted(failed_types))}."
    return NodeState.UNKNOWN, "Insufficient probe evidence to determine node state."