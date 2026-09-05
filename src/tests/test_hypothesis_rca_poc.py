from datetime import datetime, timezone

from topology_syslog.correlation.hypothesis_rca import HypothesisRCAEngine
from topology_syslog.models import SyslogMessage
from topology_syslog.topology.causal_topology import CausalTopology


def _msg(hostname: str, message: str) -> SyslogMessage:
    return SyslogMessage(
        received_at=datetime.now(tz=timezone.utc),
        source_ip="10.0.0.1",
        hostname=hostname,
        facility=3,
        severity=3,
        message=message,
    )


def _engine() -> HypothesisRCAEngine:
    return HypothesisRCAEngine(CausalTopology.from_iida_topology({
        "network-model": {
            "physical-layer": {
                "device": [
                    {
                        "device-id": "Spine1",
                        "role": "spine",
                        "loopback": "10.0.0.1/32",
                        "interface": [
                            {"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.1/30"},
                            {"interface-id": "GigabitEthernet0/1", "ip-address": "10.1.12.1/30"},
                            {"interface-id": "GigabitEthernet0/2", "ip-address": "10.1.13.1/30"},
                        ],
                    },
                    {
                        "device-id": "Leaf1",
                        "role": "leaf",
                        "loopback": "10.0.0.11/32",
                        "interface": [
                            {"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.2/30"},
                            {"interface-id": "GigabitEthernet0/2", "ip-address": "192.168.100.2/30"},
                        ],
                    },
                    {
                        "device-id": "Leaf2",
                        "role": "leaf",
                        "loopback": "10.0.0.12/32",
                        "interface": [
                            {"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.12.2/30"},
                        ],
                    },
                    {
                        "device-id": "Leaf3",
                        "role": "leaf",
                        "loopback": "10.0.0.13/32",
                        "interface": [
                            {"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.13.2/30"},
                        ],
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
                    {
                        "connection-id": "Spine1-Leaf3",
                        "endpoint": [
                            {"device-id": "Spine1", "interface-id": "GigabitEthernet0/2"},
                            {"device-id": "Leaf3", "interface-id": "GigabitEthernet0/0"},
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
                    {
                        "session-id": "Spine1-Leaf3-eBGP",
                        "type": "ebgp",
                        "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf3"}],
                    },
                ],
            },
        }
    }))


def test_poc_single_physical_link_fault_wins_over_device_fault():
    result = _engine().infer([
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
        _msg("Spine1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.1.11.1 down"),
    ])

    assert result.root_cause_object == "PhysicalLink:Leaf1:GigabitEthernet0/0--Spine1:GigabitEthernet0/0"


def test_poc_spine_device_fault_wins_when_many_downstream_sessions_fail():
    result = _engine().infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf3", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ])

    assert result.root_cause_object == "Device:Spine1"


def test_poc_leaf_access_interface_fault_stays_local():
    result = _engine().infer([
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/2, changed state to down"),
    ])

    assert result.root_cause_object == "Interface:Leaf1:GigabitEthernet0/2"


def test_poc_bgp_only_fault_stays_on_session():
    result = _engine().infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ])

    assert result.root_cause_object == "BGPSession:Spine1-Leaf1-eBGP"