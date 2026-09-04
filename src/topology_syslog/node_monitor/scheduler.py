"""ノード確認の集約、負荷制御、定期実行。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from topology_syslog.node_monitor.evaluator import evaluate_state
from topology_syslog.node_monitor.models import NodeState, NodeStateRecord, ProbeResult
from topology_syslog.node_monitor.metrics import NodeMonitorMetrics
from topology_syslog.node_monitor.probes import Probe
from topology_syslog.node_monitor.store import InMemoryNodeStateStore

_logger = logging.getLogger(__name__)


class NodeMonitor:
    def __init__(
        self,
        store: InMemoryNodeStateStore,
        probes: tuple[Probe, ...],
        *,
        ttl_sec: float = 60.0,
        min_check_interval_sec: float = 5.0,
        max_failure_backoff_sec: float = 300.0,
        max_concurrent_checks: int = 10,
        clock: Callable[[], datetime] | None = None,
        metrics: NodeMonitorMetrics | None = None,
    ) -> None:
        if (
            ttl_sec <= 0
            or min_check_interval_sec < 0
            or max_failure_backoff_sec < min_check_interval_sec
            or max_concurrent_checks < 1
        ):
            raise ValueError("invalid monitor timing or concurrency configuration")
        self._store = store
        self._probes = probes
        self._ttl = timedelta(seconds=ttl_sec)
        self._min_check_interval = timedelta(seconds=min_check_interval_sec)
        self._max_failure_backoff = timedelta(seconds=max_failure_backoff_sec)
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._semaphore = asyncio.Semaphore(max_concurrent_checks)
        self._in_flight: dict[str, asyncio.Task[NodeStateRecord]] = {}
        self._last_started: dict[str, datetime] = {}
        self._failure_counts: dict[str, int] = {}
        self._targets: dict[str, str] = {}
        self._metrics = metrics or NodeMonitorMetrics()

    def register_target(self, node_id: str, target: str) -> None:
        self._targets[node_id] = target

    def get_state(self, node_id: str) -> NodeStateRecord:
        return self._store.get(node_id, now=self._clock())

    def get_states(self, node_ids: list[str]) -> list[NodeStateRecord]:
        return self._store.get_many(node_ids, now=self._clock())

    @property
    def metrics(self) -> NodeMonitorMetrics:
        return self._metrics

    async def check(self, node_id: str, *, force: bool = False) -> NodeStateRecord:
        target = self._targets.get(node_id)
        if target is None:
            return self._store.get(node_id, now=self._clock())

        now = self._clock()
        cached = self._store.get(node_id, now=now)
        if not force and cached.state != NodeState.UNKNOWN:
            return cached

        task = self._in_flight.get(node_id)
        if task is not None:
            return await task
        if not force and self._is_rate_limited(node_id, now):
            return cached

        task = asyncio.create_task(self._run_check(node_id, target))
        self._in_flight[node_id] = task
        try:
            return await task
        finally:
            if self._in_flight.get(node_id) is task:
                del self._in_flight[node_id]

    async def run_once(self) -> list[NodeStateRecord]:
        return await asyncio.gather(*(self.check(node_id) for node_id in self._targets))

    async def run_periodically(self, interval_sec: float, stop_event: asyncio.Event) -> None:
        if interval_sec <= 0:
            raise ValueError("interval_sec must be greater than zero")
        while not stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
            except asyncio.TimeoutError:
                pass

    def _is_rate_limited(self, node_id: str, now: datetime) -> bool:
        last_started = self._last_started.get(node_id)
        if last_started is None:
            return False
        failure_count = self._failure_counts.get(node_id, 0)
        retry_interval = min(
            self._min_check_interval * (2 ** failure_count), self._max_failure_backoff
        )
        return now - last_started < retry_interval

    async def _run_check(self, node_id: str, target: str) -> NodeStateRecord:
        previous = self._store.get(node_id, now=self._clock())
        self._last_started[node_id] = self._clock()
        async with self._semaphore:
            results = await asyncio.gather(
                *(probe.probe(target) for probe in self._probes), return_exceptions=True
            )
        observed_at = self._clock()
        probe_results = tuple(
            result if isinstance(result, ProbeResult) else ProbeResult(
                probe_type=type(probe).__name__,
                target=target,
                success=None,
                observed_at=observed_at,
                error=str(result),
            )
            for probe, result in zip(self._probes, results, strict=True)
        )
        state, reason = evaluate_state(probe_results)
        if state == NodeState.UP:
            self._failure_counts.pop(node_id, None)
        else:
            self._failure_counts[node_id] = self._failure_counts.get(node_id, 0) + 1
        record = NodeStateRecord(
            node_id=node_id,
            state=state,
            observed_at=observed_at,
            expires_at=observed_at + self._ttl,
            reason=reason,
            probes=probe_results,
        )
        self._store.put(record)
        changed = previous.state != state
        self._metrics.record_check(state, changed)
        if changed:
            _logger.info(json.dumps({
                "event": "node_state_changed", "node_id": node_id,
                "previous_state": previous.state.value, "state": state.value,
                "reason": reason,
            }, sort_keys=True))
        return record