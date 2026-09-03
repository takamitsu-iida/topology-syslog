from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app
from topology_syslog.investigation.models import CommandResult, InvestigationReport
from topology_syslog.persistence.investigation_store import InvestigationStore


def _report(status: str = "completed") -> InvestigationReport:
    return InvestigationReport(
        incident_id="INC-INVESTIGATION-001",
        started_at=datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 3, 10, 1, tzinfo=timezone.utc) if status != "running" else None,
        status=status,
        summary="Interface is down.",
        command_results=[CommandResult(
            device_id="r1",
            command="show interfaces",
            output="GigabitEthernet0/0 is down",
            timestamp=datetime(2026, 9, 3, 10, 0, 30, tzinfo=timezone.utc),
        )],
    )


def test_investigation_store_persists_report_and_commands(tmp_path):
    store = InvestigationStore(f"sqlite:///{tmp_path / 'incidents.db'}")
    store.save(_report())

    restored = store.get("INC-INVESTIGATION-001")

    assert restored is not None
    assert restored.status == "completed"
    assert restored.summary == "Interface is down."
    assert restored.command_results[0].device_id == "r1"
    assert restored.command_results[0].output == "GigabitEthernet0/0 is down"


def test_investigation_store_marks_running_report_interrupted_after_restart(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'incidents.db'}"
    InvestigationStore(database_url).save(_report("running"))

    interrupted = InvestigationStore(database_url).mark_running_as_interrupted()
    restored = InvestigationStore(database_url).get("INC-INVESTIGATION-001")

    assert interrupted == 1
    assert restored is not None
    assert restored.status == "interrupted"
    assert restored.completed_at is not None
    assert restored.error == "Server restarted before the investigation completed."


def test_investigation_api_returns_persisted_report_when_agent_is_disabled(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'incidents.db'}"
    InvestigationStore(database_url).save(_report())
    app = create_app(database_url=database_url, syslog_port=0)

    with TestClient(app) as client:
        response = client.get("/incidents/INC-INVESTIGATION-001/investigation")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["commands"][0]["command"] == "show interfaces"