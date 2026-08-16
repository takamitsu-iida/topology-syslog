"""POST /ingest および WebSocket エンドポイントのテスト。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app

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
