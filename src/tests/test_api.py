import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from topology_syslog.api.main import _process_message_immediately, create_app
from topology_syslog.config import load_config
from topology_syslog.models import Incident, RCAEvidence, RCAExplanation, RCACandidate, SyslogMessage


def _make_inc(
    incident_id: str = "INC-20260816-001",
    status: str = "OPEN",
) -> Incident:
    return Incident(
        incident_id=incident_id,
        created_at=datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="%LINK-3-UPDOWN: Interface GE0/0 down",
        secondary_nodes=["Dist-Switch1", "Access-SW1"],
        raw_log_count=3,
        status=status,
    )


# ---- /incidents --------------------------------------------------------

def test_list_incidents_empty(client):
    resp = client.get("/incidents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["incidents"] == []


def test_list_incidents_with_data(client, app):
    app.state.store.save(_make_inc())
    resp = client.get("/incidents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["incidents"][0]["incident_id"] == "INC-20260816-001"
    assert body["incidents"][0]["root_cause_node"] == "Core-Router1"


def test_list_incidents_filter_by_status(client, app):
    app.state.store.save(_make_inc("INC-001", status="OPEN"))
    app.state.store.save(_make_inc("INC-002", status="CLOSED"))
    resp = client.get("/incidents", params={"status": "OPEN"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["incidents"][0]["status"] == "OPEN"


# ---- /incidents/{id} ---------------------------------------------------

def test_get_incident_found(client, app):
    app.state.store.save(_make_inc())
    resp = client.get("/incidents/INC-20260816-001")
    assert resp.status_code == 200
    assert resp.json()["incident_id"] == "INC-20260816-001"


def test_get_incident_includes_rca_explanation_without_topology_fixture():
    app = create_app(database_url="sqlite:///:memory:", syslog_port=0)
    with TestClient(app) as client:
        incident = _make_inc()
        incident.rca_explanation = RCAExplanation(
            confidence=0.65,
            primary_candidate=RCACandidate(
                node_id="Core-Router1",
                confidence=0.65,
                evidences=[RCAEvidence(source="topology", summary="upstream root", weight=0.2)],
            ),
        )
        app.state.store.save(incident)

        response = client.get("/incidents/INC-20260816-001")

        assert response.status_code == 200
        body = response.json()
        assert body["rca_explanation"]["confidence"] == 0.65
        assert body["rca_explanation"]["primary_candidate"]["node_id"] == "Core-Router1"


def test_get_rca_history_returns_evaluations_without_topology_fixture():
    app = create_app(database_url="sqlite:///:memory:", syslog_port=0)
    with TestClient(app) as client:
        incident = _make_inc()
        app.state.store.save(incident)
        app.state.store.record_rca_evaluation(
            incident.incident_id,
            RCAExplanation(
                confidence=0.91,
                primary_candidate=RCACandidate(
                    node_id="Core-Router1",
                    confidence=0.91,
                    evidences=[RCAEvidence(source="investigation", summary="confirmed down", weight=0.15)],
                ),
            ),
            reason="investigation-updated",
            evaluated_at=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
        )

        response = client.get("/incidents/INC-20260816-001/rca-history")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["evaluations"][0]["reason"] == "investigation-updated"
        assert body["evaluations"][0]["explanation"]["confidence"] == 0.91


def test_get_rca_history_missing_incident_returns_404_without_topology_fixture():
    app = create_app(database_url="sqlite:///:memory:", syslog_port=0)
    with TestClient(app) as client:
        response = client.get("/incidents/INC-MISSING/rca-history")

        assert response.status_code == 404


def test_get_incident_not_found(client):
    resp = client.get("/incidents/INC-99991231-999")
    assert resp.status_code == 404


# ---- PUT /incidents/{id}/resolve ---------------------------------------

def test_resolve_incident(client, app):
    app.state.store.save(_make_inc())
    resp = client.put("/incidents/INC-20260816-001/resolve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CLOSED"


def test_resolve_incident_not_found(client):
    resp = client.put("/incidents/INC-99991231-999/resolve")
    assert resp.status_code == 404


def test_process_message_immediately_merges_into_open_incident(app):
    with TestClient(app) as client:
        existing = Incident(
            incident_id="INC-20260816-001",
            created_at=datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc),
            root_cause_node="Dist-Switch1",
            primary_event="%LINK-3-UPDOWN: Interface GE0/0 down",
            secondary_nodes=["Access-SW1"],
            raw_log_count=1,
            raw_logs=["%LINK-3-UPDOWN: Interface GE0/0 down"],
            status="OPEN",
        )
        app.state.store.save(existing)
        msg = SyslogMessage(
            received_at=datetime(2026, 8, 16, 10, 1, 0, tzinfo=timezone.utc),
            source_ip="10.0.0.1",
            hostname="Core-Router1",
            facility=3,
            severity=5,
            message="%LINK-3-UPDOWN: Interface GE0/1 down",
        )

        class DummyNotifier:
            def __init__(self):
                self.calls = []
            def send(self, incident):
                self.calls.append(incident.incident_id)
            def resolve_by_source(self, node):
                return None

        app.state.vigil_notifier = DummyNotifier()
        with client.websocket_connect("/ws/incidents") as ws:
            asyncio.run(_process_message_immediately(app, msg))
            msg_json = ws.receive_json()
            assert msg_json["type"] == "incident.updated"
            assert msg_json["incident"]["root_cause_node"] == "Core-Router1"
            assert app.state.vigil_notifier.calls == []

        incidents = app.state.store.list_open_active()
        assert len(incidents) == 1
        assert incidents[0].incident_id == "INC-20260816-001"
        assert incidents[0].root_cause_node == "Core-Router1"
        assert incidents[0].raw_log_count >= 2


def test_create_app_accepts_time_window_compatibility_mode(tmp_path):
    cfg_path = tmp_path / "topology.yaml"
    cfg_path.write_text("topology:\n  path: configs/clos/yang_topology.yaml\n", encoding="utf-8")
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path=str(cfg_path),
        topology_source="iida-yaml",
        correlation_mode="time_window",
        window_sec=10,
    )
    assert app is not None
    assert app.state is not None


def test_load_config_warns_on_legacy_window_settings(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "correlation:\n  window_sec: 30\n",
        encoding="utf-8",
    )
    with pytest.warns(DeprecationWarning, match="Legacy correlation window settings"):
        load_config(str(cfg_path))


# ---- /topology/nodes ---------------------------------------------------

def test_topology_nodes(client):
    resp = client.get("/topology/nodes")
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert "Core-Router1" in node_ids
    assert "Dist-Switch1" in node_ids
    assert body["total"] == 5  # PoC トポロジーのノード数


def test_topology_nodes_have_role(client):
    resp = client.get("/topology/nodes")
    nodes = {n["id"]: n for n in resp.json()["nodes"]}
    assert nodes["Core-Router1"]["role"] == "core"
    assert nodes["Dist-Switch1"]["role"] == "distribution"


# ---- /topology/graph ---------------------------------------------------

def test_topology_graph_cytoscape_format(client):
    resp = client.get("/topology/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "nodes" in body["elements"]
    assert "edges" in body["elements"]


def test_topology_graph_node_count(client):
    body = client.get("/topology/graph").json()
    assert len(body["elements"]["nodes"]) == 5


def test_topology_graph_edge_count(client):
    body = client.get("/topology/graph").json()
    assert len(body["elements"]["edges"]) == 3  # PoC の physical-connection 数


def test_topology_graph_edge_has_source_target(client):
    body = client.get("/topology/graph").json()
    edge_data = [e["data"] for e in body["elements"]["edges"]]
    assert any(d["source"] == "Core-Router1" and d["target"] == "Dist-Switch1" for d in edge_data)


# ---- POST /topology/reload ---------------------------------------------

def test_topology_reload(client):
    resp = client.post("/topology/reload")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "reloaded"
    assert body["nodes"] == 5
    assert body["edges"] == 3
