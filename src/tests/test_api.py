from datetime import datetime, timezone

from topology_syslog.models import Incident


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
    app.state.store.save(_make_inc("INC-002", status="RESOLVED"))
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


def test_get_incident_not_found(client):
    resp = client.get("/incidents/INC-99991231-999")
    assert resp.status_code == 404


# ---- PUT /incidents/{id}/resolve ---------------------------------------

def test_resolve_incident(client, app):
    app.state.store.save(_make_inc())
    resp = client.put("/incidents/INC-20260816-001/resolve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "RESOLVED"


def test_resolve_incident_not_found(client):
    resp = client.put("/incidents/INC-99991231-999/resolve")
    assert resp.status_code == 404


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
