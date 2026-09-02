from datetime import datetime, timezone

import pytest

from topology_syslog.api.schemas import IncidentOut
from topology_syslog.models import Incident, RCAEvidence, RCAExplanation, RCACandidate
from topology_syslog.persistence.incident_store import IncidentStore


def _store() -> IncidentStore:
    return IncidentStore("sqlite:///:memory:")


def _inc(
    incident_id: str = "INC-20260816-001",
    status: str = "OPEN",
    condition: str = "ACTIVE",
    root_cause_node: str = "Core-Router1",
    created_at: datetime | None = None,
    last_fault_at: datetime | None = None,
    last_recovery_at: datetime | None = None,
    flap_count: int = 0,
    recovery_evidence: list[str] | None = None,
) -> Incident:
    return Incident(
        incident_id=incident_id,
        created_at=created_at or datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc),
        root_cause_node=root_cause_node,
        primary_event="%LINK-3-UPDOWN: Interface GE0/0 down",
        secondary_nodes=["Dist-Switch1", "Access-SW1"],
        raw_log_count=3,
        raw_logs=["raw-1", "raw-2", "raw-3"],
        status=status,
        condition=condition,
        last_fault_at=last_fault_at,
        last_recovery_at=last_recovery_at,
        flap_count=flap_count,
        recovery_evidence=recovery_evidence or [],
    )


def test_save_and_get_by_id():
    store = _store()
    inc = _inc()
    store.save(inc)
    result = store.get_by_id(inc.incident_id)
    assert result is not None
    assert result.incident_id == inc.incident_id
    assert result.root_cause_node == "Core-Router1"
    assert result.secondary_nodes == ["Dist-Switch1", "Access-SW1"]
    assert result.status == "OPEN"


def test_get_by_id_not_found():
    store = _store()
    assert store.get_by_id("INC-99991231-999") is None


def test_list_all():
    store = _store()
    store.save(_inc("INC-20260816-001"))
    store.save(_inc("INC-20260816-002"))
    results = store.list_incidents()
    assert len(results) == 2


def test_list_filter_by_status():
    store = _store()
    store.save(_inc("INC-20260816-001", status="OPEN"))
    store.save(_inc("INC-20260816-002", status="CLOSED"))
    open_only = store.list_incidents(status="OPEN")
    assert len(open_only) == 1
    assert open_only[0].status == "OPEN"


def test_list_filter_by_date_range():
    store = _store()
    store.save(_inc("INC-A", created_at=datetime(2026, 8, 16, 8, 0, 0, tzinfo=timezone.utc)))
    store.save(_inc("INC-B", created_at=datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc)))
    store.save(_inc("INC-C", created_at=datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)))

    from_dt = datetime(2026, 8, 16, 9, 0, 0, tzinfo=timezone.utc)
    to_dt   = datetime(2026, 8, 16, 11, 0, 0, tzinfo=timezone.utc)
    results = store.list_incidents(from_dt=from_dt, to_dt=to_dt)
    assert len(results) == 1
    assert results[0].incident_id == "INC-B"


def test_list_ordered_by_desc_created_at():
    store = _store()
    store.save(_inc("INC-OLDER", created_at=datetime(2026, 8, 16, 9, 0, 0, tzinfo=timezone.utc)))
    store.save(_inc("INC-NEWER", created_at=datetime(2026, 8, 16, 11, 0, 0, tzinfo=timezone.utc)))
    results = store.list_incidents()
    assert results[0].incident_id == "INC-NEWER"


def test_resolve_existing():
    store = _store()
    inc = _inc()
    store.save(inc)
    ok = store.resolve(inc.incident_id)
    assert ok is True
    updated = store.get_by_id(inc.incident_id)
    assert updated.status == "CLOSED"


def test_resolve_nonexistent():
    store = _store()
    ok = store.resolve("INC-99991231-999")
    assert ok is False


def test_save_overwrites_on_same_id():
    store = _store()
    inc = _inc()
    store.save(inc)
    inc_updated = Incident(
        incident_id=inc.incident_id,
        created_at=inc.created_at,
        root_cause_node=inc.root_cause_node,
        primary_event="updated event",
        secondary_nodes=[],
        raw_log_count=1,
        status="CLOSED",
    )
    store.save(inc_updated)
    result = store.get_by_id(inc.incident_id)
    assert result.primary_event == "updated event"
    assert result.status == "CLOSED"


def test_update_existing_incident_without_creating_new_row():
    store = _store()
    inc = _inc()
    store.save(inc)
    inc.root_cause_node = "Spine1"
    inc.primary_event = "%LINK-3-UPDOWN: Spine down"
    inc.secondary_nodes = ["Core-Router1", "Dist-Switch1"]
    inc.raw_log_count = 4
    inc.raw_logs = ["raw-1", "raw-2", "raw-3", "raw-4"]
    inc.condition = "FLAPPING"

    assert store.update(inc) is True
    updated = store.get_by_id(inc.incident_id)
    assert updated.root_cause_node == "Spine1"
    assert updated.primary_event == "%LINK-3-UPDOWN: Spine down"
    assert updated.secondary_nodes == ["Core-Router1", "Dist-Switch1"]
    assert updated.raw_log_count == 4
    assert updated.raw_logs == ["raw-1", "raw-2", "raw-3", "raw-4"]
    assert updated.condition == "FLAPPING"
    assert store.count() == 1


def test_update_missing_incident_returns_false():
    store = _store()
    assert store.update(_inc("INC-MISSING")) is False
    assert store.count() == 0


def test_list_open_active_returns_merge_candidates_only():
    store = _store()
    store.save(_inc("INC-ACTIVE", condition="ACTIVE", created_at=datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)))
    store.save(_inc("INC-FLAPPING", condition="FLAPPING", created_at=datetime(2026, 8, 16, 13, 0, 0, tzinfo=timezone.utc)))
    store.save(_inc("INC-RECOVERED", condition="RECOVERED"))
    store.save(_inc("INC-CLOSED", status="CLOSED", condition="ACTIVE"))

    results = store.list_open_active()
    assert [inc.incident_id for inc in results] == ["INC-FLAPPING", "INC-ACTIVE"]


def test_list_open_lifecycle_returns_recovery_candidates():
    store = _store()
    store.save(_inc("INC-ACTIVE", condition="ACTIVE"))
    store.save(_inc("INC-DEGRADED", condition="DEGRADED"))
    store.save(_inc("INC-RECOVERING", condition="RECOVERING"))
    store.save(_inc("INC-RECOVERED", condition="RECOVERED"))
    store.save(_inc("INC-CLOSED", status="CLOSED", condition="RECOVERING"))

    results = store.list_open_lifecycle()

    assert {inc.incident_id for inc in results} == {"INC-ACTIVE", "INC-DEGRADED", "INC-RECOVERING", "INC-RECOVERED"}


def test_incident_lifecycle_fields_are_persisted():
    store = _store()
    last_fault_at = datetime(2026, 8, 16, 10, 5, 0, tzinfo=timezone.utc)
    last_recovery_at = datetime(2026, 8, 16, 10, 7, 0, tzinfo=timezone.utc)
    store.save(_inc(
        condition="RECOVERING",
        last_fault_at=last_fault_at,
        last_recovery_at=last_recovery_at,
        flap_count=2,
        recovery_evidence=["%LINK-3-UPDOWN: Interface GE0/0 up"],
    ))

    result = store.get_by_id("INC-20260816-001")

    assert result is not None
    assert result.condition == "RECOVERING"
    assert result.last_fault_at == last_fault_at
    assert result.last_recovery_at == last_recovery_at
    assert result.flap_count == 2
    assert result.recovery_evidence == ["%LINK-3-UPDOWN: Interface GE0/0 up"]


def test_update_persists_incident_lifecycle_fields():
    store = _store()
    incident = _inc()
    store.save(incident)
    incident.condition = "DEGRADED"
    incident.last_fault_at = datetime(2026, 8, 16, 10, 8, 0, tzinfo=timezone.utc)
    incident.last_recovery_at = datetime(2026, 8, 16, 10, 9, 0, tzinfo=timezone.utc)
    incident.flap_count = 3
    incident.recovery_evidence = ["BGP neighbor established"]

    assert store.update(incident) is True
    updated = store.get_by_id(incident.incident_id)

    assert updated is not None
    assert updated.condition == "DEGRADED"
    assert updated.last_fault_at == incident.last_fault_at
    assert updated.last_recovery_at == incident.last_recovery_at
    assert updated.flap_count == 3
    assert updated.recovery_evidence == ["BGP neighbor established"]


def test_save_and_get_persists_rca_explanation():
    store = _store()
    incident = _inc()
    incident.rca_explanation = RCAExplanation(
        confidence=0.86,
        primary_candidate=RCACandidate(
            node_id="Core-Router1",
            confidence=0.86,
            evidences=[RCAEvidence(
                source="topology",
                summary="Core-Router1 is upstream of affected switches",
                weight=0.2,
                related_nodes=["Core-Router1", "Dist-Switch1"],
                related_log_ids=["1"],
            )],
            secondary_nodes=["Dist-Switch1"],
        ),
        alternative_candidates=[RCACandidate(
            node_id="Dist-Switch1",
            confidence=0.31,
            alternative_reason="has upstream fault candidate",
        )],
    )

    store.save(incident)
    result = store.get_by_id(incident.incident_id)

    assert result is not None
    assert result.rca_explanation.confidence == 0.86
    assert result.rca_explanation.primary_candidate.node_id == "Core-Router1"
    assert result.rca_explanation.primary_candidate.evidences[0].source == "topology"
    assert result.rca_explanation.alternative_candidates[0].node_id == "Dist-Switch1"


def test_incident_out_includes_rca_explanation():
    incident = _inc()
    incident.rca_explanation = RCAExplanation(
        confidence=0.72,
        primary_candidate=RCACandidate(
            node_id="Core-Router1",
            confidence=0.72,
            evidences=[RCAEvidence(source="syslog", summary="link down", weight=0.3)],
        ),
    )

    payload = IncidentOut.model_validate(incident).model_dump(mode="json")

    assert payload["rca_explanation"]["confidence"] == 0.72
    assert payload["rca_explanation"]["primary_candidate"]["node_id"] == "Core-Router1"
    assert payload["rca_explanation"]["primary_candidate"]["evidences"][0]["source"] == "syslog"


def test_record_rca_evaluation_updates_current_explanation_and_history():
    store = _store()
    incident = _inc()
    store.save(incident)
    explanation = RCAExplanation(
        confidence=0.91,
        primary_candidate=RCACandidate(
            node_id="Core-Router1",
            confidence=0.91,
            evidences=[RCAEvidence(source="investigation", summary="interface is down", weight=0.15)],
        ),
    )

    record = store.record_rca_evaluation(
        incident.incident_id,
        explanation,
        reason="investigation-updated",
        evaluated_at=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
    )
    updated = store.get_by_id(incident.incident_id)
    history = store.list_rca_history(incident.incident_id)

    assert record is not None
    assert record.reason == "investigation-updated"
    assert updated.rca_explanation.confidence == 0.91
    assert len(history) == 1
    assert history[0].explanation.primary_candidate.evidences[0].source == "investigation"


def test_record_rca_evaluation_missing_incident_returns_none():
    store = _store()
    assert store.record_rca_evaluation("INC-MISSING", RCAExplanation(confidence=0.1)) is None
    assert store.list_rca_history("INC-MISSING") == []


def test_created_at_tz_preserved():
    store = _store()
    inc = _inc()
    store.save(inc)
    result = store.get_by_id(inc.incident_id)
    assert result.created_at.tzinfo is not None
    assert result.created_at == inc.created_at
