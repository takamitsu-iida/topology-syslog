from datetime import datetime, timezone

from topology_syslog.correlation.recovery_matcher import (
    RecoveryMatcher,
    RecoveryMatchScope,
    extract_interface,
    extract_peer,
)
from topology_syslog.ingestion.syslog_parser import parse
from topology_syslog.models import Incident


def _incident(
    incident_id: str = "INC-20260902-001",
    status: str = "OPEN",
    root_cause_node: str = "Spine1",
) -> Incident:
    return Incident(
        incident_id=incident_id,
        created_at=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
        root_cause_node=root_cause_node,
        primary_event="%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
        secondary_nodes=["Leaf1", "Leaf2"],
        raw_log_count=2,
        raw_logs=[
            "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
            "%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down",
        ],
        status=status,
    )


def test_extracts_interface_and_peer_from_recovery_messages():
    assert extract_interface("%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up") == "GigabitEthernet0/0"
    assert extract_peer("%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Up") == "10.0.0.1"


def test_recovery_matcher_matches_root_node_recovery():
    recovery = parse(
        b"<34>Sep  2 10:05:00 Spine1 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up",
        "10.0.0.1",
    )

    matches = RecoveryMatcher().find_matches(recovery, [_incident()])

    assert any(match.scope == RecoveryMatchScope.ROOT for match in matches)
    assert any(match.scope == RecoveryMatchScope.INTERFACE and match.matched_interface == "GigabitEthernet0/0" for match in matches)


def test_recovery_matcher_matches_secondary_node_recovery():
    recovery = parse(
        b"<34>Sep  2 10:05:00 Leaf1 %BGP-5-ADJCHANGE: neighbor 10.0.0.1 Up",
        "10.0.0.11",
    )

    matches = RecoveryMatcher().find_matches(recovery, [_incident()])

    assert any(match.scope == RecoveryMatchScope.SECONDARY and match.matched_node == "Leaf1" for match in matches)
    assert any(match.scope == RecoveryMatchScope.PEER and match.matched_peer == "10.0.0.1" for match in matches)


def test_recovery_matcher_ignores_non_recovery_and_closed_incidents():
    fault = parse(
        b"<34>Sep  2 10:00:00 Spine1 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
        "10.0.0.1",
    )

    assert RecoveryMatcher().find_matches(fault, [_incident()]) == []

    recovery = parse(
        b"<34>Sep  2 10:05:00 Spine1 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up",
        "10.0.0.1",
    )
    assert RecoveryMatcher().find_matches(recovery, [_incident(status="CLOSED")]) == []