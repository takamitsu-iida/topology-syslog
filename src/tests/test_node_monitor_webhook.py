from __future__ import annotations

import asyncio

import httpx

from topology_syslog.node_monitor.models import NodeState, NodeStateChangeEvent, ProbeResult
from topology_syslog.node_monitor.webhook import WebhookEventPublisher


def _event() -> NodeStateChangeEvent:
    from datetime import datetime, timezone

    observed_at = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    return NodeStateChangeEvent(
        event_id="node-state-Spine2-test-DOWN",
        event_type="node_state.changed",
        node_id="Spine2",
        previous_state=NodeState.UP,
        state=NodeState.DOWN,
        observed_at=observed_at,
        reason="probes failed",
        probes=(ProbeResult("icmp", "10.0.0.2", False, observed_at),),
    )


def test_webhook_publisher_retries_and_sends_bearer_token(monkeypatch):
    calls: list[dict] = []

    class _Response:
        def raise_for_status(self):
            pass

    async def post(self, url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _Response()

    async def scenario():
        publisher = WebhookEventPublisher("http://backend/events", token="event-token", backoff_sec=0)
        monkeypatch.setattr(httpx.AsyncClient, "post", post)
        await publisher.start()
        publisher.publish(_event())
        await publisher._queue.join()
        await publisher.close()

    asyncio.run(scenario())

    assert len(calls) == 1
    assert calls[0]["headers"] == {"Authorization": "Bearer event-token"}
    assert calls[0]["json"]["event_id"] == "node-state-Spine2-test-DOWN"


def test_webhook_publisher_drops_when_queue_is_full():
    publisher = WebhookEventPublisher("http://backend/events", token="token", queue_size=1)

    publisher.publish(_event())
    publisher.publish(_event())

    assert publisher.dropped_events == 1
