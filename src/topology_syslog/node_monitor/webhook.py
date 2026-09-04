"""状態変化イベントを backend へ非同期配送する webhook publisher。"""
from __future__ import annotations

import asyncio
import logging
import httpx

from topology_syslog.node_monitor.models import NodeStateChangeEvent

_logger = logging.getLogger(__name__)


class WebhookEventPublisher:
    def __init__(
        self,
        url: str,
        *,
        token: str,
        timeout_sec: float = 2.0,
        max_retries: int = 3,
        queue_size: int = 1000,
        backoff_sec: float = 0.5,
    ) -> None:
        if not url or not token or timeout_sec <= 0 or max_retries < 0 or queue_size < 1 or backoff_sec < 0:
            raise ValueError("invalid webhook publisher configuration")
        self._url = url
        self._token = token
        self._timeout_sec = timeout_sec
        self._max_retries = max_retries
        self._backoff_sec = backoff_sec
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=queue_size)
        self._client: httpx.AsyncClient | None = None
        self._worker: asyncio.Task[None] | None = None
        self.dropped_events = 0

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._client = httpx.AsyncClient(timeout=self._timeout_sec)
        self._worker = asyncio.create_task(self._run())

    def publish(self, event: NodeStateChangeEvent) -> None:
        """イベントをキューへ積む。HTTP送信は呼び出し元をブロックしない。"""
        payload = _event_to_dict(event)
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.dropped_events += 1
            _logger.error("node state event queue is full; event dropped: %s", event.event_id)

    async def close(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        if self._client is not None:
            await self._client.aclose()
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        self._worker = None
        self._client = None

    async def _run(self) -> None:
        while True:
            payload = await self._queue.get()
            try:
                await self._deliver(payload)
            finally:
                self._queue.task_done()

    async def _deliver(self, payload: dict) -> None:
        if self._client is None:
            return
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(
                    self._url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                response.raise_for_status()
                return
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    _logger.error("node state event delivery failed: %s", payload["event_id"], exc_info=exc)
                    return
                await asyncio.sleep(self._backoff_sec * (2 ** attempt))


def _event_to_dict(event: NodeStateChangeEvent) -> dict:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "node_id": event.node_id,
        "previous_state": event.previous_state.value,
        "state": event.state.value,
        "observed_at": event.observed_at.isoformat(),
        "reason": event.reason,
        "probes": [
            {
                "probe_type": probe.probe_type,
                "target": probe.target,
                "success": probe.success,
                "observed_at": probe.observed_at.isoformat(),
                "latency_ms": probe.latency_ms,
                "error": probe.error,
            }
            for probe in event.probes
        ],
    }