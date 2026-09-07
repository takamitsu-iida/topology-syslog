from datetime import datetime, timezone

from topology_syslog.correlation.observation import ObservationNormalizer
from topology_syslog.knowledge.classifier import EventClassifier
from topology_syslog.knowledge.store import KnowledgeRule
from topology_syslog.models import EventAction, EventClassification, SyslogMessage
from topology_syslog.topology.causal_topology import CausalTopology


def _msg(
    hostname: str,
    message: str,
    *,
    source_ip: str = "10.0.0.1",
    is_recovery: bool = False,
) -> SyslogMessage:
    event_type = None
    if "%LINK-3-UPDOWN" in message:
        event_type = "%LINK-3-UPDOWN"
    elif "%BGP-5-ADJCHANGE" in message:
        event_type = "%BGP-5-ADJCHANGE"
    return SyslogMessage(
        received_at=datetime.now(tz=timezone.utc),
        source_ip=source_ip,
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
                        "loopback": "10.0.0.1/32",
                        "interface": [{"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.1/30"}],
                    },
                    {
                        "device-id": "Leaf1",
                        "loopback": "10.0.0.11/32",
                        "interface": [
                            {"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.2/30"},
                            {"interface-id": "GigabitEthernet0/2", "ip-address": "192.168.100.2/30"},
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
                "lacp-session": [{
                    "session-id": "Leaf1-Port-channel1",
                    "endpoint": [{"device-id": "Leaf1", "interface-id": "Port-channel1"}],
                }],
            },
        }
    })


def test_link_updown_syslog_becomes_interface_fault_observation():
    message = _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down")
    rule = KnowledgeRule(
        rule_id="link-down",
        signature="%LINK-*-UPDOWN",
        classification="fault-signal",
        correlation_role="root-cause-candidate",
        severity_policy={"0-7": "create_incident"},
        confidence=0.95,
    )
    EventClassifier().classify(message, rule)

    observation = ObservationNormalizer(_topology()).normalize(message, rule)

    assert observation is not None
    assert observation.observed_object == "Interface:Leaf1:GigabitEthernet0/0"
    assert observation.assertion == "fault"
    assert observation.classification == EventClassification.FAULT_SIGNAL.value
    assert observation.action == EventAction.CREATE_INCIDENT.value
    assert observation.knowledge_id == "link-down"
    assert observation.confidence == 0.95


def test_source_ip_resolves_syslog_without_topology_hostname():
    message = _msg("10.0.0.1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down")

    observation = ObservationNormalizer(_topology()).normalize(message)

    assert observation is not None
    assert observation.source_node == "Spine1"
    assert observation.observed_object == "Interface:Spine1:GigabitEthernet0/0"


def test_bgp_adjchange_peer_ip_becomes_bgp_session_observation():
    message = _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.1.11.1 down")
    rule = KnowledgeRule(
        rule_id="bgp-down",
        signature="%BGP-*-ADJCHANGE",
        classification="bgp-adjacency-change",
        correlation_role="secondary-impact",
        severity_policy={"0-7": "correlate_only"},
        confidence=0.9,
    )
    EventClassifier().classify(message, rule)

    observation = ObservationNormalizer(_topology()).normalize(message, rule)

    assert observation is not None
    assert observation.observed_object == "BGPSession:Spine1-Leaf1-eBGP"
    assert observation.assertion == "state_change"
    assert observation.action == EventAction.CORRELATE_ONLY.value
    assert observation.confidence == 0.9


def test_bgp_adjchange_peer_hostname_becomes_bgp_session_observation():
    message = _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down")
    EventClassifier().classify(message)

    observation = ObservationNormalizer(_topology()).normalize(message)

    assert observation is not None
    assert observation.observed_object == "BGPSession:Spine1-Leaf1-eBGP"


def test_ospf_adjchg_reason_does_not_become_interface_named_down():
    topology = CausalTopology.load_from_iida_yaml("configs/ospf/yang_topology.yaml")
    message = _msg(
        "Leaf3",
        "%OSPF-5-ADJCHG: Process 1, Nbr 10.0.0.1 on GigabitEthernet0/0 "
        "from FULL to DOWN, Neighbor Down: Interface down or detached",
    )
    EventClassifier().classify(message)

    observation = ObservationNormalizer(topology).normalize(message)

    assert observation is not None
    assert observation.observed_object == "OSPFSession:Spine1-Leaf3-OSPF"
    assert observation.peer_device == "Spine1"


def test_lacp_event_becomes_lacp_session_observation():
    message = _msg("Leaf1", "%LACP-4-PORTCHANNEL: Interface Port-channel1, changed state to down")
    rule = KnowledgeRule(
        rule_id="lacp-down",
        signature="%LACP-*-*",
        classification="lacp-state-change",
        correlation_role="secondary-impact",
        severity_policy={"0-7": "correlate_only"},
        confidence=0.9,
    )
    EventClassifier().classify(message, rule)

    observation = ObservationNormalizer(_topology()).normalize(message, rule)

    assert observation is not None
    assert observation.observed_object == "LACPSession:Leaf1-Port-channel1"
    assert observation.assertion == "state_change"
    assert observation.action == EventAction.CORRELATE_ONLY.value


def test_unknown_syslog_becomes_low_confidence_device_fault_observation():
    message = _msg("Leaf1", "%NEW-3-EVENT: something unusual happened")
    EventClassifier().classify(message)

    observation = ObservationNormalizer(_topology()).normalize(message)

    assert observation is not None
    assert observation.observed_object == "Device:Leaf1"
    assert observation.assertion == "fault"
    assert observation.classification == EventClassification.UNKNOWN.value
    assert observation.action == EventAction.REVIEW.value
    assert observation.confidence == 0.35


def test_retain_only_classification_becomes_noise_observation():
    message = _msg("Leaf1", "%SYS-5-CONFIG_I: configured from console")
    rule = KnowledgeRule(
        rule_id="config-change",
        signature="%SYS-*-CONFIG_I",
        classification="configuration-change",
        correlation_role="informational",
        severity_policy={"0-7": "retain_only"},
        confidence=0.99,
    )
    EventClassifier().classify(message, rule)

    observation = ObservationNormalizer(_topology()).normalize(message, rule)

    assert observation is not None
    assert observation.observed_object == "Device:Leaf1"
    assert observation.assertion == "noise"
    assert observation.action == EventAction.RETAIN_ONLY.value
    assert observation.confidence == 0.2


def test_recovery_syslog_becomes_recovery_observation():
    message = _msg(
        "Leaf1",
        "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up",
        is_recovery=True,
    )
    rule = KnowledgeRule(
        rule_id="link-updown",
        signature="%LINK-*-UPDOWN",
        classification="link-state-change",
        correlation_role="root-cause-candidate",
        severity_policy={"0-7": "create_incident"},
        confidence=0.95,
    )
    EventClassifier().classify(message, rule)

    observation = ObservationNormalizer(_topology()).normalize(message, rule)

    assert observation is not None
    assert observation.observed_object == "Interface:Leaf1:GigabitEthernet0/0"
    assert observation.assertion == "recovery"
    assert observation.confidence == 0.95


def test_unknown_host_does_not_create_observation():
    message = _msg(
        "Unknown",
        "%LINK-3-UPDOWN: Interface GigabitEthernet0/0 down",
        source_ip="192.0.2.99",
    )

    assert ObservationNormalizer(_topology()).normalize(message) is None