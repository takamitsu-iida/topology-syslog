from datetime import datetime, timezone

import httpx

from topology_syslog.node_monitor.client import HttpNodeStateReader
from topology_syslog.node_monitor.models import NodeState


def test_http_node_state_reader_returns_unknown_when_monitor_is_unavailable(monkeypatch):
    reader = HttpNodeStateReader("http://node-monitor:8090")

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(reader._client, "get", unavailable)
    now = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)

    actual = reader.get("Spine2", now=now)
    reader.close()

    assert actual.node_id == "Spine2"
    assert actual.state == NodeState.UNKNOWN
    assert "unavailable" in actual.reason


def test_http_node_state_reader_sends_configured_bearer_token():
    reader = HttpNodeStateReader("http://node-monitor:8090", auth_token="monitor-token")

    assert reader._client.headers["authorization"] == "Bearer monitor-token"

    reader.close()