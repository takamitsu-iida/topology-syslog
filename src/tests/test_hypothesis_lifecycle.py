from datetime import datetime, timedelta, timezone

from topology_syslog.correlation.hypothesis_lifecycle import HypothesisIncidentLifecycle, HypothesisLifecycleEventType
from topology_syslog.correlation.hypothesis_rca import HypothesisRCAEngine
from topology_syslog.correlation.incident_projector import IncidentProjector
from topology_syslog.correlation.observation import ObservationNormalizer
from topology_syslog.models import IncidentCondition, SyslogMessage
from topology_syslog.topology.causal_topology import CausalTopology


BASE = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)


def _msg(hostname: str, message: str, seconds: int = 0, *, is_recovery: bool = False) -> SyslogMessage:
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
        is_recovery=is_recovery,
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
                        "interface": [
                            {"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.2/30"},
                            {"interface-id": "GigabitEthernet0/1", "ip-address": "192.0.2.1/30"},
                        ],
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


def _project_link_incident(topology: CausalTopology):
    result = HypothesisRCAEngine(topology).infer([
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 0),
        _msg("Spine1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 1),
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.1.11.1 down", 2),
    ])
    event = IncidentProjector(topology).project(result)
    assert event is not None
    return event.incident


def _observation(topology: CausalTopology, message: SyslogMessage):
    observation = ObservationNormalizer(topology).normalize(message)
    assert observation is not None
    return observation


def test_link_recovery_moves_related_projected_incident_to_recovering():
    topology = _topology()
    incident = _project_link_incident(topology)
    recovery = _observation(
        topology,
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up", 10, is_recovery=True),
    )

    event = HypothesisIncidentLifecycle(topology).apply_recovery(incident, recovery)

    assert event.event_type == HypothesisLifecycleEventType.RECOVERING
    assert incident.condition == IncidentCondition.RECOVERING.value
    assert incident.last_recovery_at == BASE + timedelta(seconds=10)
    assert incident.recovery_evidence == ["%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up"]


def test_device_recovery_moves_projected_device_incident_to_recovering():
    topology = _topology()
    result = HypothesisRCAEngine(topology).infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down", 0),
    ])
    event = IncidentProjector(topology).project(result)
    assert event is not None
    incident = event.incident
    recovery = _observation(topology, _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 up", 5, is_recovery=True))

    lifecycle_event = HypothesisIncidentLifecycle(topology).apply_recovery(incident, recovery)

    assert lifecycle_event.event_type == HypothesisLifecycleEventType.RECOVERING
    assert incident.condition == IncidentCondition.RECOVERING.value


def test_unrelated_recovery_observation_does_not_change_incident():
    topology = _topology()
    incident = _project_link_incident(topology)
    recovery = _observation(
        topology,
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up", 10, is_recovery=True),
    )

    event = HypothesisIncidentLifecycle(topology).apply_recovery(incident, recovery)

    assert event.event_type == HypothesisLifecycleEventType.NO_MATCH
    assert incident.condition == IncidentCondition.ACTIVE.value


def test_confirm_recovered_after_quiet_period():
    topology = _topology()
    incident = _project_link_incident(topology)
    recovery = _observation(
        topology,
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up", 10, is_recovery=True),
    )
    lifecycle = HypothesisIncidentLifecycle(topology, quiet_period_sec=30)
    lifecycle.apply_recovery(incident, recovery)

    too_early = lifecycle.confirm_recovered(incident, BASE + timedelta(seconds=20))
    recovered = lifecycle.confirm_recovered(incident, BASE + timedelta(seconds=40))

    assert too_early.event_type == HypothesisLifecycleEventType.NO_MATCH
    assert recovered.event_type == HypothesisLifecycleEventType.RECOVERED
    assert incident.condition == IncidentCondition.RECOVERED.value


def test_fault_after_recovery_marks_flapping_at_threshold():
    topology = _topology()
    incident = _project_link_incident(topology)
    recovery = _observation(
        topology,
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up", 10, is_recovery=True),
    )
    fault = _observation(
        topology,
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 20),
    )
    lifecycle = HypothesisIncidentLifecycle(topology, flap_threshold=1)
    lifecycle.apply_recovery(incident, recovery)

    event = lifecycle.apply_fault(incident, fault)

    assert event.event_type == HypothesisLifecycleEventType.FLAPPING
    assert incident.condition == IncidentCondition.FLAPPING.value
    assert incident.flap_count == 1