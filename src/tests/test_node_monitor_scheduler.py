from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from topology_syslog.node_monitor.models import NodeState, ProbeResult
from topology_syslog.node_monitor.scheduler import NodeMonitor
from topology_syslog.node_monitor.store import InMemoryNodeStateStore


class _Probe:
    def __init__(self, probe_type: str, success: bool, started: asyncio.Event | None = None) -> None:
        self._probe_type = probe_type
        self._success = success
        self._started = started
        self.calls = 0
        self.release = asyncio.Event()

    async def probe(self, target: str) -> ProbeResult:
        self.calls += 1
        if self._started is not None:
            self._started.set()
            await self.release.wait()
        return ProbeResult(self._probe_type, target, self._success, _NOW)


_NOW = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)


def _monitor(probes, *, now: datetime = _NOW, ttl_sec: float = 60.0, min_interval: float = 5.0):
    monitor = NodeMonitor(
        InMemoryNodeStateStore(), tuple(probes), ttl_sec=ttl_sec,
        min_check_interval_sec=min_interval, clock=lambda: now,
    )
    monitor.register_target("Spine2", "10.0.0.2")
    return monitor


def test_concurrent_checks_for_same_node_share_one_probe_execution():
    started = asyncio.Event()
    probe = _Probe("icmp", True, started)
    monitor = _monitor([probe])

    async def check_twice():
        first = asyncio.create_task(monitor.check("Spine2"))
        await started.wait()
        second = asyncio.create_task(monitor.check("Spine2"))
        probe.release.set()
        return await asyncio.gather(first, second)

    first, second = asyncio.run(check_twice())

    assert probe.calls == 1
    assert first == second
    assert first.state == NodeState.UP


def test_unexpired_state_is_reused_without_reprobing():
    probe = _Probe("icmp", True)
    monitor = _monitor([probe])

    asyncio.run(monitor.check("Spine2"))
    actual = asyncio.run(monitor.check("Spine2"))

    assert probe.calls == 1
    assert actual.state == NodeState.UP


def test_rate_limit_prevents_immediate_retry_after_unknown_result():
    probe = _Probe("icmp", False)
    monitor = _monitor([probe], min_interval=5.0)

    asyncio.run(monitor.check("Spine2"))
    actual = asyncio.run(monitor.check("Spine2"))

    assert probe.calls == 1
    assert actual.state == NodeState.UNKNOWN


def test_run_once_checks_registered_targets():
    probe = _Probe("icmp", True)
    monitor = _monitor([probe])
    monitor.register_target("Spine1", "10.0.0.1")

    states = asyncio.run(monitor.run_once())

    assert {state.node_id for state in states} == {"Spine1", "Spine2"}
    assert probe.calls == 2


def test_expired_state_is_checked_again():
    probe = _Probe("icmp", True)
    current_time = _NOW
    monitor = NodeMonitor(
        InMemoryNodeStateStore(), (probe,), ttl_sec=60, min_check_interval_sec=0,
        clock=lambda: current_time,
    )
    monitor.register_target("Spine2", "10.0.0.2")

    asyncio.run(monitor.check("Spine2"))
    current_time = _NOW + timedelta(seconds=61)
    asyncio.run(monitor.check("Spine2"))

    assert probe.calls == 2


def test_failed_check_uses_exponential_backoff_before_retrying():
    probe = _Probe("icmp", False)
    current_time = _NOW
    monitor = NodeMonitor(
        InMemoryNodeStateStore(), (probe,), ttl_sec=1, min_check_interval_sec=5,
        max_failure_backoff_sec=30, clock=lambda: current_time,
    )
    monitor.register_target("Spine2", "10.0.0.2")

    asyncio.run(monitor.check("Spine2"))
    current_time += timedelta(seconds=6)
    asyncio.run(monitor.check("Spine2"))
    current_time += timedelta(seconds=9)
    asyncio.run(monitor.check("Spine2"))
    current_time += timedelta(seconds=1)
    asyncio.run(monitor.check("Spine2"))

    assert probe.calls == 2