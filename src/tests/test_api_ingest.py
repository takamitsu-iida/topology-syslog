"""POST /ingest および WebSocket エンドポイントのテスト。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from topology_syslog.api.main import _can_create_inferred_incident, _process_message_immediately, create_app
from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
from topology_syslog.ingestion.file_ingest import run_batch
from topology_syslog.ingestion.syslog_parser import parse
from topology_syslog.models import EventAction, EventClassification, EventClassificationResult, Incident
from topology_syslog.persistence.incident_store import IncidentStore

# RFC 3164 形式のテスト用シスログ行
_CHAIN_MSGS = [
    {
        "source_ip": "192.168.1.1",
        "raw": "<34>Aug 16 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface GE0/0 down",
    },
    {
        "source_ip": "192.168.1.2",
        "raw": "<34>Aug 16 10:00:01 Dist-Switch1 %BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down",
    },
    {
        "source_ip": "192.168.1.3",
        "raw": "<34>Aug 16 10:00:02 Access-SW1 %PING-3-FAILED: gateway unreachable",
    },
]


@pytest.fixture
def client_no_topo():
    _app = create_app(database_url="sqlite:///:memory:")
    with TestClient(_app) as c:
        yield c


# ---- POST /ingest -------------------------------------------------------

def test_ingest_chain_creates_one_incident(client):
    resp = client.post("/ingest", json={"messages": _CHAIN_MSGS})
    assert resp.status_code == 200
    incidents = resp.json()
    assert len(incidents) == 1
    assert incidents[0]["root_cause_node"] == "Core-Router1"
    assert set(incidents[0]["secondary_nodes"]) == {"Dist-Switch1", "Access-SW1"}


def test_silent_root_incident_is_allowed_for_correlate_only_event():
    incident = Incident(
        incident_id="INC-SILENT-001",
        created_at=datetime.now(tz=timezone.utc),
        root_cause_node="Spine2",
        primary_event="(inferred — node did not send SYSLOG)",
    )
    classification = EventClassificationResult(
        classification=EventClassification.STATE_CHANGE,
        action=EventAction.CORRELATE_ONLY,
    )

    assert _can_create_inferred_incident(incident, classification, enforce=True)


def test_ingest_creates_silent_spine2_incident_from_leaf2_bgp():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        knowledge_path="configs/syslog_knowledge",
    )
    with TestClient(app) as client:
        response = client.post("/ingest", json={"messages": [{
            "source_ip": "127.0.0.1",
            "raw": "<37>Sep 5 06:07:25 Leaf2 %BGP-5-ADJCHANGE: neighbor 10.2.12.1 Down BGP Notification sent",
        }]})

    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) == 1
    assert incidents[0]["root_cause_node"] == "Spine2"
    assert incidents[0]["secondary_nodes"] == ["Leaf2"]


def test_ingest_creates_silent_leaf2_incident_from_both_spines_bgp():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        knowledge_path="configs/syslog_knowledge",
    )
    with TestClient(app) as client:
        response = client.post("/ingest", json={"messages": [
            {
                "source_ip": "127.0.0.1",
                "raw": "<37>Sep 5 06:53:33 Spine2 %BGP-5-ADJCHANGE: neighbor 10.2.12.2 Down BGP Notification sent",
            },
            {
                "source_ip": "127.0.0.1",
                "raw": "<37>Sep 5 06:53:36 Spine1 %BGP-5-ADJCHANGE: neighbor 10.1.12.2 Down BGP Notification sent",
            },
        ]})

    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) == 1
    assert incidents[0]["root_cause_node"] == "Leaf2"
    assert set(incidents[0]["secondary_nodes"]) == {"Spine1", "Spine2"}
    assert incidents[0]["raw_log_count"] == 2


def test_ingest_creates_silent_leaf3_incident_from_spine_session_removal():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        knowledge_path="configs/syslog_knowledge",
    )
    with TestClient(app) as client:
        response = client.post("/ingest", json={"messages": [{
            "source_ip": "127.0.0.1",
            "raw": (
                "<37>Sep 5 07:05:53.510 Spine2 %BGP_SESSION-5-ADJCHANGE: "
                "neighbor 10.2.13.2 IPv4 Unicast topology base removed from session BGP "
                "Notification sent"
            ),
        }]})

    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) == 1
    assert incidents[0]["root_cause_node"] == "Leaf3"
    assert incidents[0]["secondary_nodes"] == ["Spine2"]


def test_ingest_unknown_hosts_returns_empty(client):
    resp = client.post("/ingest", json={"messages": [
        {"source_ip": "1.2.3.4", "raw": "<34>Aug 16 10:00:00 Ghost1 some error"},
        {"source_ip": "1.2.3.5", "raw": "<34>Aug 16 10:00:01 Ghost2 some error"},
    ]})
    assert resp.status_code == 200
    assert resp.json() == []


def test_ingest_without_topology_returns_503(client_no_topo):
    resp = client_no_topo.post("/ingest", json={"messages": _CHAIN_MSGS})
    assert resp.status_code == 503


def test_ingest_saves_incident_to_store(client, app):
    resp = client.post("/ingest", json={"messages": _CHAIN_MSGS})
    assert resp.status_code == 200
    incident_id = resp.json()[0]["incident_id"]
    stored = app.state.store.get_by_id(incident_id)
    assert stored is not None
    assert stored.root_cause_node == "Core-Router1"


def test_ingest_incident_id_format(client):
    resp = client.post("/ingest", json={"messages": _CHAIN_MSGS})
    assert resp.status_code == 200
    iid = resp.json()[0]["incident_id"]
    assert iid.startswith("INC-")
    parts = iid.split("-")
    assert len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit()


def test_ingest_uses_immediate_pipeline_to_promote_existing_root_cause(client, app):
    existing = Incident(
        incident_id="INC-OLD-001",
        created_at=datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc),
        root_cause_node="Dist-Switch1",
        primary_event="%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down",
        secondary_nodes=["Access-SW1"],
        raw_log_count=1,
        raw_logs=["%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down"],
        status="OPEN",
    )
    app.state.store.save(existing)

    response = client.post("/ingest", json={"messages": [
        {
            "source_ip": "192.168.1.1",
            "raw": "<34>Aug 16 10:00:01 Core-Router1 %LINK-3-UPDOWN: Interface GE0/0 down",
        },
    ]})

    assert response.status_code == 200
    assert response.json()[0]["incident_id"] == "INC-OLD-001"
    merged = app.state.store.get_by_id("INC-OLD-001")
    assert merged is not None
    assert merged.root_cause_node == "Core-Router1"
    assert "Dist-Switch1" in merged.secondary_nodes


def test_ingest_uses_immediate_pipeline_for_recovery(client, app):
    fault = parse(
        b"<34>Aug 16 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
        "192.168.1.1",
    )
    __import__("asyncio").run(_process_message_immediately(app, fault))

    response = client.post("/ingest", json={"messages": [
        {
            "source_ip": "192.168.1.1",
            "raw": "<34>Aug 16 10:00:01 Core-Router1 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up",
        },
    ]})

    assert response.status_code == 200
    assert len(response.json()) == 1
    incident = app.state.store.get_by_id(response.json()[0]["incident_id"])
    assert incident is not None
    assert incident.condition == "RECOVERING"


def test_udp_and_ingest_produce_equivalent_incident_state(poc_topology_file):
    udp_app = create_app(
        database_url="sqlite:///:memory:", topology_path=poc_topology_file,
        topology_source="iida-yaml", syslog_port=0,
    )
    api_app = create_app(
        database_url="sqlite:///:memory:", topology_path=poc_topology_file,
        topology_source="iida-yaml", syslog_port=0,
    )
    with TestClient(udp_app), TestClient(api_app) as api_client:
        for item in _CHAIN_MSGS:
            message = parse(item["raw"].encode(), item["source_ip"])
            __import__("asyncio").run(_process_message_immediately(udp_app, message))
        response = api_client.post("/ingest", json={"messages": _CHAIN_MSGS})

    assert response.status_code == 200
    udp_incidents = udp_app.state.store.list_incidents()
    api_incidents = api_app.state.store.list_incidents()
    assert len(udp_incidents) == len(api_incidents) == 1
    assert udp_incidents[0].root_cause_node == api_incidents[0].root_cause_node
    assert udp_incidents[0].secondary_nodes == api_incidents[0].secondary_nodes
    assert udp_incidents[0].raw_log_count == api_incidents[0].raw_log_count


# ---- WebSocket ----------------------------------------------------------

def test_websocket_connects(client):
    with client.websocket_connect("/ws/incidents") as ws:
        assert ws is not None


def test_websocket_connection_count(client, app):
    assert app.state.ws_manager.connection_count == 0
    with client.websocket_connect("/ws/incidents"):
        assert app.state.ws_manager.connection_count == 1
    assert app.state.ws_manager.connection_count == 0


def test_ingest_broadcasts_to_websocket(client):
    with client.websocket_connect("/ws/incidents") as ws:
        client.post("/ingest", json={"messages": _CHAIN_MSGS})
        msg = ws.receive_json()
        assert msg["type"] == "incident.new"
        assert msg["incident"]["root_cause_node"] == "Core-Router1"


def test_run_batch_merges_later_upstream_root_cause_into_open_incident(poc_engine, tmp_path):
    store = IncidentStore("sqlite:///:memory:")
    store.save(Incident(
        incident_id="INC-OLD-001",
        created_at=datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc),
        root_cause_node="Dist-Switch1",
        primary_event="%LINK-3-UPDOWN: Interface GE0/0 down",
        secondary_nodes=["Access-SW1"],
        raw_log_count=1,
        raw_logs=["%LINK-3-UPDOWN: Interface GE0/0 down"],
        status="OPEN",
    ))

    log_path = tmp_path / "batch.log"
    log_path.write_text(
        "<34>Aug 16 10:00:01 Core-Router1 %LINK-3-UPDOWN: Interface GE0/1 down\n",
        encoding="utf-8",
    )

    count = run_batch(
        str(log_path),
        poc_engine,
        RootCauseInferencer(),
        store=store,
    )

    assert count == 1
    merged = store.get_by_id("INC-OLD-001")
    assert merged is not None
    assert merged.root_cause_node == "Core-Router1"
    assert "Dist-Switch1" in merged.secondary_nodes
