from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from topology_syslog.node_monitor.api import create_app
from topology_syslog.node_monitor.metrics import NodeMonitorMetrics
from topology_syslog.node_monitor.models import NodeState, NodeStateRecord
from topology_syslog.node_monitor.scheduler import NodeMonitor
from topology_syslog.node_monitor.store import InMemoryNodeStateStore


_NOW = datetime.now(tz=timezone.utc)


def _client() -> TestClient:
    store = InMemoryNodeStateStore()
    store.put(NodeStateRecord(
        node_id="Spine2", state=NodeState.DOWN, observed_at=_NOW,
        expires_at=_NOW + timedelta(minutes=1), reason="Independent probes failed.",
    ))
    monitor = NodeMonitor(store, (), clock=lambda: _NOW)
    return TestClient(create_app(monitor, interval_sec=60))


def test_healthz_returns_ok():
    with _client() as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_node_state_returns_current_record():
    with _client() as client:
        response = client.get("/v1/nodes/Spine2/state")

    assert response.status_code == 200
    assert response.json()["state"] == "DOWN"
    assert response.json()["reason"] == "Independent probes failed."


def test_get_node_states_returns_requested_order_and_unknown_nodes():
    with _client() as client:
        response = client.get("/v1/nodes/states", params=[("node_id", "Leaf1"), ("node_id", "Spine2")])

    assert response.status_code == 200
    assert [state["node_id"] for state in response.json()] == ["Leaf1", "Spine2"]
    assert [state["state"] for state in response.json()] == ["UNKNOWN", "DOWN"]


def test_api_requires_bearer_token_when_configured():
    app = create_app(NodeMonitor(InMemoryNodeStateStore(), ()), auth_token="monitor-token")
    with TestClient(app) as client:
        unauthorized = client.get("/v1/nodes/Spine2/state")
        authorized = client.get("/v1/nodes/Spine2/state", headers={"Authorization": "Bearer monitor-token"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_metrics_endpoint_returns_prometheus_format():
    metrics = NodeMonitorMetrics()
    metrics.record_check(NodeState.DOWN, changed=True)
    monitor = NodeMonitor(InMemoryNodeStateStore(), (), metrics=metrics)
    with TestClient(create_app(monitor)) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert 'node_monitor_checks_total{state="DOWN"} 1' in response.text
    assert 'node_monitor_state_changes_total{state="DOWN"} 1' in response.text