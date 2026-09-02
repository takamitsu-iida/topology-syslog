from datetime import datetime, timezone

from topology_syslog.correlation.incident_lifecycle import IncidentLifecycle
from topology_syslog.correlation.recovery_matcher import RecoveryMatch, RecoveryMatchScope
from topology_syslog.models import Incident, IncidentCondition, SyslogMessage


def _incident(condition: str = "ACTIVE", status: str = "OPEN") -> Incident:
    return Incident(
        incident_id="INC-20260902-001",
        created_at=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
        root_cause_node="Spine1",
        primary_event="%LINK-3-UPDOWN: Interface GigabitEthernet0/0 down",
        secondary_nodes=["Leaf1"],
        raw_log_count=1,
        raw_logs=["%LINK-3-UPDOWN: Interface GigabitEthernet0/0 down"],
        status=status,
        condition=condition,
    )


def _message() -> SyslogMessage:
    return SyslogMessage(
        received_at=datetime(2026, 9, 2, 10, 5, tzinfo=timezone.utc),
        source_ip="10.0.0.1",
        hostname="Spine1",
        facility=4,
        severity=3,
        message="%LINK-3-UPDOWN: Interface GigabitEthernet0/0 down",
    )


def test_root_recovery_moves_incident_to_recovering_and_records_evidence():
    incident = _incident()
    at = datetime(2026, 9, 2, 10, 10, tzinfo=timezone.utc)
    match = RecoveryMatch(
        incident=incident,
        scope=RecoveryMatchScope.ROOT,
        matched_node="Spine1",
        evidence="%LINK-3-UPDOWN: Interface GigabitEthernet0/0 up",
    )

    updated = IncidentLifecycle().apply_recovery(incident, [match], at)

    assert updated.condition == IncidentCondition.RECOVERING.value
    assert updated.last_recovery_at == at
    assert updated.recovery_evidence == ["%LINK-3-UPDOWN: Interface GigabitEthernet0/0 up"]


def test_secondary_recovery_moves_incident_to_degraded():
    incident = _incident()
    at = datetime(2026, 9, 2, 10, 10, tzinfo=timezone.utc)
    match = RecoveryMatch(
        incident=incident,
        scope=RecoveryMatchScope.SECONDARY,
        matched_node="Leaf1",
        evidence="%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Up",
    )

    updated = IncidentLifecycle().apply_recovery(incident, [match], at)

    assert updated.condition == IncidentCondition.DEGRADED.value
    assert updated.last_recovery_at == at
    assert updated.recovery_evidence == ["%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Up"]


def test_fault_during_recovering_marks_active_then_flapping():
    lifecycle = IncidentLifecycle()
    incident = _incident(condition=IncidentCondition.RECOVERING.value)
    message = _message()

    lifecycle.apply_fault(incident, message, flap_threshold=2)
    assert incident.condition == IncidentCondition.ACTIVE.value
    assert incident.flap_count == 1
    assert incident.last_fault_at == message.received_at

    lifecycle.apply_fault(incident, message, flap_threshold=2)
    assert incident.condition == IncidentCondition.FLAPPING.value
    assert incident.flap_count == 2


def test_mark_recovered_sets_recovered_without_closing():
    incident = _incident(condition=IncidentCondition.RECOVERING.value)
    at = datetime(2026, 9, 2, 10, 15, tzinfo=timezone.utc)

    updated = IncidentLifecycle().mark_recovered(incident, at)

    assert updated.status == "OPEN"
    assert updated.condition == IncidentCondition.RECOVERED.value
    assert updated.last_recovery_at == at


def test_closed_incident_is_not_changed_by_lifecycle():
    incident = _incident(status="CLOSED")
    original_condition = incident.condition

    IncidentLifecycle().apply_fault(incident, _message())

    assert incident.condition == original_condition


def test_fault_after_recovery_seen_prevents_recovered_confirmation():
    incident = _incident(condition=IncidentCondition.RECOVERING.value)
    recovery_seen_at = datetime(2026, 9, 2, 10, 10, tzinfo=timezone.utc)
    incident.last_recovery_at = recovery_seen_at

    message = _message()
    message.received_at = datetime(2026, 9, 2, 10, 11, tzinfo=timezone.utc)
    IncidentLifecycle().apply_fault(incident, message)

    assert incident.last_fault_at > recovery_seen_at
    assert incident.condition == IncidentCondition.ACTIVE.value