from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from topology_syslog.node_monitor.evaluator import evaluate_state
from topology_syslog.node_monitor.models import NodeState, ProbeResult
from topology_syslog.node_monitor.probes import IcmpProbe, TcpProbe


_OBSERVED_AT = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)


class _Writer:
    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


def _result(probe_type: str, success: bool | None) -> ProbeResult:
    return ProbeResult(probe_type, "10.0.0.2", success, _OBSERVED_AT)


def test_tcp_probe_only_opens_and_closes_connection(monkeypatch):
    calls: list[tuple[str, int]] = []

    async def open_connection(host: str, port: int):
        calls.append((host, port))
        return object(), _Writer()

    monkeypatch.setattr(asyncio, "open_connection", open_connection)

    result = asyncio.run(TcpProbe(179).probe("10.0.0.2"))

    assert calls == [("10.0.0.2", 179)]
    assert result.success is True
    assert result.target == "10.0.0.2:179"


def test_tcp_probe_returns_failure_when_connection_is_refused(monkeypatch):
    async def open_connection(host: str, port: int):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(asyncio, "open_connection", open_connection)

    result = asyncio.run(TcpProbe(179).probe("10.0.0.2"))

    assert result.success is False
    assert "refused" in result.error


def test_probes_reject_non_ip_target():
    with pytest.raises(ValueError, match="IP address"):
        asyncio.run(IcmpProbe().probe("Spine2; shutdown -h now"))


def test_evaluate_state_requires_two_distinct_failures_for_down():
    state, reason = evaluate_state((_result("icmp", False), _result("tcp/179", False)))

    assert state == NodeState.DOWN
    assert "icmp" in reason


def test_evaluate_state_marks_required_probe_failure_as_degraded():
    state, _ = evaluate_state(
        (_result("icmp", True), _result("tcp/179", False)),
        required_probe_types=frozenset({"tcp/179"}),
    )

    assert state == NodeState.DEGRADED


def test_evaluate_state_does_not_claim_down_from_one_failure():
    state, _ = evaluate_state((_result("icmp", False),))

    assert state == NodeState.UNKNOWN