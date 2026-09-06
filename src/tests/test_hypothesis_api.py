import time
from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app


def test_hypothesis_ingest_creates_new_incident_for_different_leaf2_link_after_recovery():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        syslog_port=0,
    )

    with TestClient(app) as client:
        first_down = client.post("/ingest", json={"messages": [
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:06.021 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down",
            },
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:06.022 Spine2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down",
            },
        ]})
        first_up = client.post("/ingest", json={"messages": [
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:07.021 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up",
            },
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:07.022 Spine2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up",
            },
        ]})
        second_down = client.post("/ingest", json={"messages": [
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:20.021 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
            },
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:20.022 Spine1 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down",
            },
        ]})
        incidents = client.get("/incidents?include_children=true").json()["incidents"]

    assert first_down.status_code == 200
    assert first_up.status_code == 200
    assert second_down.status_code == 200
    assert len(incidents) == 2
    root_objects = {
        incident["rca_explanation"]["primary_candidate"]["evidences"][0]["related_log_ids"][0]
        for incident in incidents
    }
    assert root_objects == {
        "PhysicalLink:Leaf2:GigabitEthernet0/1--Spine2:GigabitEthernet0/1",
        "PhysicalLink:Leaf2:GigabitEthernet0/0--Spine1:GigabitEthernet0/1",
    }


def test_hypothesis_ingest_recreates_incident_after_same_interface_recovers(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'interface-lifecycle.db'}",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        recovery_quiet_period_sec=0.01,
        syslog_port=0,
    )
    down = "<35>Sep 6 08:00:00 Spine2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down"
    up = "<35>Sep 6 08:00:01 Spine2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up"

    with TestClient(app) as client:
        first = client.post("/ingest", json={"messages": [{"source_ip": "127.0.0.1", "raw": down}]})
        first_incident_id = first.json()[0]["incident_id"]

        recovery = client.post("/ingest", json={"messages": [{"source_ip": "127.0.0.1", "raw": up}]})
        time.sleep(0.05)
        recovered = app.state.store.get_by_id(first_incident_id)

        second = client.post("/ingest", json={"messages": [{"source_ip": "127.0.0.1", "raw": down}]})
        incidents = app.state.store.list_incidents()

    assert first.status_code == 200
    assert recovery.status_code == 200
    assert second.status_code == 200
    assert recovered is not None
    assert recovered.condition == "RECOVERED"
    assert len(incidents) == 2
    assert second.json()[0]["incident_id"] != first_incident_id
    assert {incident.incident_id for incident in incidents} == {
        first_incident_id,
        second.json()[0]["incident_id"],
    }


def test_hypothesis_ingest_recreates_incident_after_same_link_recovers(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'link-lifecycle.db'}",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        recovery_quiet_period_sec=0.01,
        syslog_port=0,
    )
    down = [
        {"source_ip": "127.0.0.1", "raw": "<35>Sep 6 08:10:00 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down"},
        {"source_ip": "127.0.0.1", "raw": "<35>Sep 6 08:10:00 Spine2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down"},
    ]
    up = [
        {"source_ip": "127.0.0.1", "raw": "<35>Sep 6 08:10:01 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up"},
        {"source_ip": "127.0.0.1", "raw": "<35>Sep 6 08:10:01 Spine2 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up"},
    ]

    with TestClient(app) as client:
        first = client.post("/ingest", json={"messages": down})
        first_incident_id = first.json()[0]["incident_id"]
        recovery = client.post("/ingest", json={"messages": up})
        time.sleep(0.05)
        recovered = app.state.store.get_by_id(first_incident_id)
        second = client.post("/ingest", json={"messages": down})
        incidents = app.state.store.list_incidents()

    assert first.status_code == 200
    assert recovery.status_code == 200
    assert second.status_code == 200
    assert recovered is not None
    assert recovered.condition == "RECOVERED"
    assert len(incidents) == 2
    assert second.json()[0]["incident_id"] != first_incident_id


def test_hypothesis_ingest_persists_bgp_impact_as_child_incident():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        syslog_port=0,
    )

    with TestClient(app) as client:
        response = client.post("/ingest", json={"messages": [
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:06.021 Leaf2 %BGP-5-ADJCHANGE: neighbor Spine1 down",
            },
        ]})
        incidents = client.get("/incidents?include_children=true").json()["incidents"]

    assert response.status_code == 200
    parent = next(incident for incident in incidents if incident["relationship_type"] == "root")
    child = next(incident for incident in incidents if incident["relationship_type"] == "impact")
    assert parent["child_incident_ids"] == [child["incident_id"]]
    assert child["parent_incident_id"] == parent["incident_id"]
    assert child["root_cause_object"].startswith("BGPSession:")
