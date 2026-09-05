from datetime import datetime, timedelta, timezone

from topology_syslog.correlation.observation import Observation, ObservationNormalizer
from topology_syslog.correlation.observation_buffer import BufferUpdateType, ObservationBuffer
from topology_syslog.models import SyslogMessage
from topology_syslog.topology.causal_topology import CausalTopology


BASE = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)


def _msg(hostname: str, message: str, seconds: int) -> SyslogMessage:
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
                        "interface": [
                            {"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.1/30"},
                            {"interface-id": "GigabitEthernet0/1", "ip-address": "10.1.12.1/30"},
                        ],
                    },
                    {
                        "device-id": "Leaf1",
                        "interface": [{"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.2/30"}],
                    },
                    {
                        "device-id": "Leaf2",
                        "interface": [{"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.12.2/30"}],
                    },
                ],
                "physical-connection": [
                    {
                        "connection-id": "Spine1-Leaf1",
                        "endpoint": [
                            {"device-id": "Spine1", "interface-id": "GigabitEthernet0/0"},
                            {"device-id": "Leaf1", "interface-id": "GigabitEthernet0/0"},
                        ],
                    },
                    {
                        "connection-id": "Spine1-Leaf2",
                        "endpoint": [
                            {"device-id": "Spine1", "interface-id": "GigabitEthernet0/1"},
                            {"device-id": "Leaf2", "interface-id": "GigabitEthernet0/0"},
                        ],
                    },
                ],
            },
            "layer3-layer": {
                "bgp-session": [
                    {
                        "session-id": "Spine1-Leaf1-eBGP",
                        "type": "ebgp",
                        "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf1"}],
                    },
                    {
                        "session-id": "Spine1-Leaf2-eBGP",
                        "type": "ebgp",
                        "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf2"}],
                    },
                ],
            },
        }
    })


def _observation(topology: CausalTopology, message: SyslogMessage) -> Observation:
    observation = ObservationNormalizer(topology).normalize(message)
    assert observation is not None
    return observation


def test_buffer_returns_tentative_result_before_window_closes():
    topology = _topology()
    buffer = ObservationBuffer(topology, window_sec=10, early_confidence=0.3)

    update = buffer.add(_observation(topology, _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down", 0)))

    assert update.update_type == BufferUpdateType.TENTATIVE
    assert update.current_root_cause_object == "BGPSession:Spine1-Leaf1-eBGP"
    assert update.result is not None


def test_buffer_revises_rca_when_delayed_link_evidence_arrives():
    topology = _topology()
    buffer = ObservationBuffer(topology, window_sec=10, early_confidence=0.3)

    first = buffer.add(_observation(topology, _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.1.11.1 down", 2)))
    second = buffer.add(_observation(topology, _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 0)))
    third = buffer.add(_observation(topology, _msg("Spine1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 1)))

    assert first.current_root_cause_object == "BGPSession:Spine1-Leaf1-eBGP"
    revised = next(update for update in (second, third) if update.update_type == BufferUpdateType.RCA_REVISED)
    assert revised.previous_root_cause_object != revised.current_root_cause_object
    assert revised.current_root_cause_object == "PhysicalLink:Leaf1:GigabitEthernet0/0--Spine1:GigabitEthernet0/0"


def test_buffer_keeps_event_time_order_separate_from_received_time():
    topology = _topology()
    buffer = ObservationBuffer(topology, window_sec=10, early_confidence=0.3)
    late_received = _observation(topology, _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 0))
    early_received = _observation(topology, _msg("Spine1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down", 1))

    buffer.add(early_received, received_at=BASE + timedelta(seconds=20))
    update = buffer.add(late_received, received_at=BASE + timedelta(seconds=30))

    assert update.result is not None
    assert [observation.observed_at for observation in update.result.observations] == [BASE, BASE + timedelta(seconds=1)]
    assert buffer.observations[0].received_at == BASE + timedelta(seconds=20)
    assert buffer.observations[1].received_at == BASE + timedelta(seconds=30)


def test_buffer_closes_window_when_event_time_exceeds_window():
    topology = _topology()
    buffer = ObservationBuffer(topology, window_sec=5, early_confidence=0.3)

    buffer.add(_observation(topology, _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down", 0)))
    update = buffer.add(_observation(topology, _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor Spine1 down", 10)))

    assert update.update_type == BufferUpdateType.TENTATIVE
    assert len(buffer.observations) == 1
    assert buffer.observations[0].source_node == "Leaf2"


def test_close_window_returns_final_result_and_clears_buffer():
    topology = _topology()
    buffer = ObservationBuffer(topology, window_sec=10, early_confidence=0.3)

    buffer.add(_observation(topology, _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down", 0)))
    update = buffer.close_window()

    assert update.update_type == BufferUpdateType.WINDOW_CLOSED
    assert update.result is not None
    assert update.current_root_cause_object == "BGPSession:Spine1-Leaf1-eBGP"
    assert buffer.observations == ()