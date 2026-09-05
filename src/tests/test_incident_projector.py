from datetime import datetime, timedelta, timezone

from topology_syslog.correlation.hypothesis_rca import HypothesisRCAEngine
from topology_syslog.correlation.incident_projector import IncidentProjector, ProjectionEventType
from topology_syslog.models import Incident
from topology_syslog.topology.causal_topology import CausalTopology
from topology_syslog.models import SyslogMessage


BASE = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)


def _msg(hostname: str, message: str, seconds: int = 0) -> SyslogMessage:
    event_type = None
    if "%LINK-3-UPDOWN" in message:
        event_type = "%LINK-3-UPDOWN"
    elif "%BGP-5-ADJCHANGE" in message:
        event_type = "%BGP-5-ADJCHANGE"
    return SyslogMessage(
        received_at=BASE + timedelta(seconds=seconds),
        source_ip="10.0.0.1",
        hostname=hostname,
        facility=3,
        severity=3,
        message=message,
        event_type=event_type,
    )


def _topology() -> CausalTopology:
    return CausalTopology.from_iida_topology({
        "network-model": {
            "physical-layer": {
                "device": [
                    {
                        "device-id": "Spine1",
                        "interface": [{"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.1/30"}],
                    },
                    {
                        "device-id": "Leaf1",
                        "interface": [{"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.2/30"}],
                    },
                ],
                "physical-connection": [{
                    "connection-id": "Spine1-Leaf1",
                    "endpoint": [
                        {"device-id": "Spine1", "interface-id": "GigabitEthernet0/0"},
                        {"device-id": "Leaf1", "interface-id": "GigabitEthernet0/0"},
                    ],
                }],
            },
            "layer3-layer": {
                "bgp-session": [{
                    "session-id": "Spine1-Leaf1-eBGP",
                    "type": "ebgp",
                    "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf1"}],
                }],
            },
        }
    })


def test_projector_creates_legacy_incident_from_rca_result():
    topology = _topology()
    result = HypothesisRCAEngine(topology).infer([
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 0),
        _msg("Spine1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 1),
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.1.11.1 down", 2),
    ])

    event = IncidentProjector(topology).project(result)

    assert event is not None
    assert event.event_type == ProjectionEventType.INCIDENT_CANDIDATE
    assert isinstance(event.incident, Incident)
    assert event.root_cause_object == "PhysicalLink:Leaf1:GigabitEthernet0/0--Spine1:GigabitEthernet0/0"
    assert event.incident.root_cause_node == "Spine1"
    assert event.incident.incident_id == "INC-20260905-001"
    assert event.incident.created_at == BASE
    assert event.incident.raw_log_count == 3
    assert len(event.incident.raw_logs) == 3


def test_projector_builds_secondary_nodes_and_primary_event_from_observations():
    topology = _topology()
    result = HypothesisRCAEngine(topology).infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down", 0),
        _msg("Spine1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 1),
    ])

    event = IncidentProjector(topology).project(result)

    assert event is not None
    assert event.incident.primary_event == "%BGP-5-ADJCHANGE: neighbor Spine1 down"
    assert event.incident.secondary_nodes == ["Leaf1"]
    assert event.incident.last_fault_at == BASE + timedelta(seconds=1)


def test_projector_preserves_score_components_in_rca_explanation():
    topology = _topology()
    result = HypothesisRCAEngine(topology).infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down", 0),
    ])

    event = IncidentProjector(topology).project(result)

    assert event is not None
    explanation = event.incident.rca_explanation
    assert explanation.confidence == result.confidence
    assert explanation.primary_candidate is not None
    assert explanation.primary_candidate.node_id == "Spine1"
    assert {evidence.source for evidence in explanation.primary_candidate.evidences} == {"hypothesis-score"}
    assert any(evidence.summary.startswith("coverage:") for evidence in explanation.primary_candidate.evidences)


def test_projector_emits_revision_event_without_store_integration():
    topology = _topology()
    result = HypothesisRCAEngine(topology).infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down", 0),
    ])

    event = IncidentProjector(topology).project(
        result,
        previous_root_cause_object="BGPSession:old",
        projected_at=BASE + timedelta(seconds=5),
    )

    assert event is not None
    assert event.event_type == ProjectionEventType.RCA_REVISED
    assert event.previous_root_cause_object == "BGPSession:old"
    assert event.root_cause_object == result.root_cause_object
    assert event.incident.created_at == BASE + timedelta(seconds=5)


def test_projector_returns_none_for_empty_rca_result():
    topology = _topology()
    result = HypothesisRCAEngine(topology).infer([])

    assert IncidentProjector(topology).project(result) is None