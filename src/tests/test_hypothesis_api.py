import pytest
from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app


def test_create_app_rejects_invalid_rca_engine():
    with pytest.raises(ValueError, match="RCA_ENGINE must be one of"):
        create_app(database_url="sqlite:///:memory:", rca_engine="invalid")


def test_debug_status_reports_hypothesis_engine_state():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        rca_engine="dual",
        syslog_port=0,
    )

    with TestClient(app) as client:
        response = client.get("/debug/status")

    assert response.status_code == 200
    body = response.json()
    assert body["rca_engine"] == "dual"
    assert body["causal_topology_loaded"] is True


def test_debug_hypothesis_rca_returns_legacy_and_hypothesis_diff_without_saving():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        rca_engine="dual",
        syslog_port=0,
    )

    with TestClient(app) as client:
        response = client.post("/debug/rca/hypothesis", json={"messages": [
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:06.021 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
            },
            {
                "source_ip": "127.0.0.1",
                "raw": "<35>Sep 5 08:13:06.021 Spine1 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down",
            },
        ]})

    assert response.status_code == 200
    body = response.json()
    assert body["legacy"]["incident_count"] >= 1
    assert body["hypothesis"]["available"] is True
    assert body["hypothesis"]["root_cause_object"] == "PhysicalLink:Leaf2:GigabitEthernet0/0--Spine1:GigabitEthernet0/1"
    assert body["hypothesis"]["projected_incident"] is not None
    assert body["diff"]["hypothesis_root"] == body["hypothesis"]["root_cause_object"]
    assert app.state.store.count() == 0
    assert app.state.last_rca_comparison == body


def test_dual_mode_ingest_keeps_legacy_response_and_records_comparison():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        rca_engine="dual",
        syslog_port=0,
    )

    with TestClient(app) as client:
        response = client.post("/ingest", json={"messages": [{
            "source_ip": "127.0.0.1",
            "raw": "<35>Sep 5 08:13:06.021 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
        }]})

    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) == 1
    assert app.state.store.count() == 1
    assert app.state.last_rca_comparison is not None
    assert app.state.last_rca_comparison["mode"] == "dual"
    assert app.state.last_rca_comparison["hypothesis"]["available"] is True


def test_migration_readiness_api_evaluates_labeled_samples_without_saving():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        rca_engine="dual",
        syslog_port=0,
    )

    with TestClient(app) as client:
        response = client.post("/debug/rca/migration-readiness", json={
            "min_accuracy": 0.5,
            "min_confidence": 0.3,
            "samples": [
                {
                    "sample_id": "clos-link-spine1-leaf2",
                    "expected_root_cause_object": "PhysicalLink:Leaf2:GigabitEthernet0/0--Spine1:GigabitEthernet0/1",
                    "expected_legacy_nodes": ["Leaf2", "Spine1"],
                    "messages": [
                        {
                            "source_ip": "127.0.0.1",
                            "raw": "<35>Sep 5 08:13:06.021 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
                        },
                        {
                            "source_ip": "127.0.0.1",
                            "raw": "<35>Sep 5 08:13:06.021 Spine1 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down",
                        },
                    ],
                }
            ],
        })
        status = client.get("/debug/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["recommended_engine"] == "hypothesis"
    assert body["rollback_engine"] == "legacy"
    assert body["samples"][0]["hypothesis_matches_expected"] is True
    assert app.state.store.count() == 0
    assert status.json()["last_rca_migration_readiness"] == body


def test_migration_readiness_api_keeps_dual_when_samples_miss():
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path="configs/clos/yang_topology.yaml",
        topology_source="iida-yaml",
        rca_engine="dual",
        syslog_port=0,
    )

    with TestClient(app) as client:
        response = client.post("/debug/rca/migration-readiness", json={
            "min_accuracy": 1.0,
            "min_confidence": 0.9,
            "samples": [
                {
                    "sample_id": "wrong-expectation",
                    "expected_root_cause_object": "Device:Spine2",
                    "messages": [{
                        "source_ip": "127.0.0.1",
                        "raw": "<35>Sep 5 08:13:06.021 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
                    }],
                }
            ],
        })

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["recommended_engine"] == "dual"
    assert body["rollback_engine"] == "legacy"