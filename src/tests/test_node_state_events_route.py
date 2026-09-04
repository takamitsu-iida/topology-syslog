from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app
from topology_syslog.persistence.node_state_event_store import NodeStateEventStore


def test_node_state_event_endpoint_requires_token_and_is_idempotent(tmp_path):
    token = "event-token"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'events.db'}",
        syslog_port=0,
        node_monitor_event_token=token,
    )
    payload = {"event_id": "event-1", "event_type": "node_state.changed", "node_id": "Spine2", "state": "DOWN"}

    with TestClient(app) as client:
        unauthorized = client.post("/internal/node-state-events", json=payload)
        first = client.post("/internal/node-state-events", json=payload, headers={"Authorization": f"Bearer {token}"})
        duplicate = client.post("/internal/node-state-events", json=payload, headers={"Authorization": f"Bearer {token}"})

    assert unauthorized.status_code == 401
    assert first.json()["status"] == "accepted"
    assert first.json()["duplicate"] is False
    assert first.json()["event_id"] == "event-1"
    assert first.json()["related_incident_ids"] == []
    assert first.json()["updated_incident_ids"] == []
    assert duplicate.json()["duplicate"] is True


def test_node_state_event_matches_root_cause_and_secondary_incidents(client, app):
    from datetime import datetime, timezone

    from topology_syslog.models import Incident

    app.state.store.save(Incident(
        incident_id="INC-ROOT",
        created_at=datetime.now(tz=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="link down",
        secondary_nodes=["Dist-Switch1"],
    ))
    app.state.node_monitor_event_token = "event-token"
    payload = {
        "event_id": "event-root",
        "event_type": "node_state.changed",
        "node_id": "Core-Router1",
        "state": "DOWN",
    }

    response = client.post(
        "/internal/node-state-events",
        json=payload,
        headers={"Authorization": "Bearer event-token"},
    )

    assert response.status_code == 200
    assert response.json()["related_incident_ids"] == ["INC-ROOT"]
    assert response.json()["match_type"] == "root_cause"


def test_node_state_event_matches_topology_when_node_is_not_listed(client, app):
    from datetime import datetime, timezone

    from topology_syslog.models import Incident

    app.state.store.save(Incident(
        incident_id="INC-TOPOLOGY",
        created_at=datetime.now(tz=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="link down",
        secondary_nodes=[],
    ))
    app.state.node_monitor_event_token = "event-token"
    payload = {
        "event_id": "event-topology",
        "event_type": "node_state.changed",
        "node_id": "Dist-Switch1",
        "state": "DOWN",
    }

    response = client.post(
        "/internal/node-state-events",
        json=payload,
        headers={"Authorization": "Bearer event-token"},
    )

    assert response.status_code == 200
    assert response.json()["related_incident_ids"] == ["INC-TOPOLOGY"]
    assert response.json()["match_type"] == "topology"


def test_down_event_updates_evidence_condition_and_rca_history(client, app):
    from datetime import datetime, timezone

    from topology_syslog.models import Incident

    incident = Incident(
        incident_id="INC-UPDATE",
        created_at=datetime.now(tz=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="link down",
        secondary_nodes=[],
    )
    app.state.store.save(incident)
    app.state.node_monitor_event_token = "event-token"

    response = client.post(
        "/internal/node-state-events",
        json={
            "event_id": "event-update",
            "event_type": "node_state.changed",
            "node_id": "Core-Router1",
            "state": "DOWN",
            "observed_at": "2026-09-04T10:00:05+00:00",
            "reason": "icmp and tcp failed",
            "probes": [{"probe_type": "icmp", "target": "10.0.0.1", "success": False}],
        },
        headers={"Authorization": "Bearer event-token"},
    )

    updated = app.state.store.get_by_id("INC-UPDATE")
    assert response.json()["updated_incident_ids"] == ["INC-UPDATE"]
    assert updated is not None
    assert updated.condition == "DEGRADED"
    assert updated.rca_explanation.confidence == 0.30
    assert updated.rca_explanation.primary_candidate.evidences[0].source == "node-monitor"
    assert len(app.state.store.list_rca_history("INC-UPDATE")) == 1


def test_up_event_adds_recovery_evidence_without_closing_incident(client, app):
    from datetime import datetime, timezone

    from topology_syslog.models import Incident

    app.state.store.save(Incident(
        incident_id="INC-RECOVERY",
        created_at=datetime.now(tz=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="link down",
    ))
    app.state.node_monitor_event_token = "event-token"

    client.post(
        "/internal/node-state-events",
        json={
            "event_id": "event-up",
            "event_type": "node_state.changed",
            "node_id": "Core-Router1",
            "state": "UP",
        },
        headers={"Authorization": "Bearer event-token"},
    )

    updated = app.state.store.get_by_id("INC-RECOVERY")
    assert updated is not None
    assert updated.status == "OPEN"
    assert updated.condition == "ACTIVE"
    assert updated.rca_explanation.primary_candidate.evidences[0].source == "node-monitor"


def test_down_up_events_recover_after_quiet_period(tmp_path):
    from datetime import datetime, timezone
    from topology_syslog.models import Incident

    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'recovery.db'}",
        syslog_port=0,
        node_monitor_event_token="event-token",
        recovery_quiet_period_sec=0.01,
    )
    with TestClient(app) as test_client:
        app.state.store.save(Incident(
            incident_id="INC-QUIET",
            created_at=datetime.now(tz=timezone.utc),
            root_cause_node="Core-Router1",
            primary_event="link down",
        ))
        down = {"event_id": "event-down", "event_type": "node_state.changed", "node_id": "Core-Router1", "state": "DOWN", "observed_at": "2026-09-04T10:00:00+00:00"}
        up = {"event_id": "event-up-quiet", "event_type": "node_state.changed", "node_id": "Core-Router1", "state": "UP", "observed_at": "2026-09-04T10:00:01+00:00"}
        test_client.post("/internal/node-state-events", json=down, headers={"Authorization": "Bearer event-token"})
        test_client.post("/internal/node-state-events", json=up, headers={"Authorization": "Bearer event-token"})
        import time
        time.sleep(0.05)
        restored = app.state.store.get_by_id("INC-QUIET")

    assert restored is not None
    assert restored.condition == "RECOVERED"


def test_stale_event_is_accepted_but_not_applied(client, app):
    from datetime import datetime, timezone
    from topology_syslog.models import Incident

    app.state.store.save(Incident(
        incident_id="INC-STALE",
        created_at=datetime.now(tz=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="link down",
    ))
    app.state.node_monitor_event_token = "event-token"
    headers = {"Authorization": "Bearer event-token"}
    newer = {"event_id": "event-new", "event_type": "node_state.changed", "node_id": "Core-Router1", "state": "DOWN", "observed_at": "2026-09-04T10:00:02+00:00"}
    older = {"event_id": "event-old", "event_type": "node_state.changed", "node_id": "Core-Router1", "state": "UP", "observed_at": "2026-09-04T10:00:01+00:00"}

    client.post("/internal/node-state-events", json=newer, headers=headers)
    response = client.post("/internal/node-state-events", json=older, headers=headers)

    assert response.json()["stale"] is True
    assert response.json()["updated_incident_ids"] == []
    assert app.state.store.get_by_id("INC-STALE").condition == "DEGRADED"