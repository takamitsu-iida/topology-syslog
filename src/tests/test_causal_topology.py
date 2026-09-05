from pathlib import Path

import pytest

from topology_syslog.topology.causal_topology import (
    CausalTopology,
    InterfaceEndpoint,
    bgp_session_object_id,
    device_object_id,
    interface_object_id,
    physical_link_object_id,
)

_ROOT = Path(__file__).parent.parent.parent
CLOS_YAML = _ROOT / "configs" / "clos" / "yang_topology.yaml"


def test_clos_causal_object_counts():
    topology = CausalTopology.load_from_iida_yaml(CLOS_YAML)

    assert len(topology.objects_by_type("device")) == 5
    assert len(topology.objects_by_type("interface")) == 13
    assert len(topology.objects_by_type("physical-link")) == 6
    assert len(topology.objects_by_type("bgp-session")) == 9


def test_clos_causal_topology_has_stable_object_ids_and_attributes():
    topology = CausalTopology.load_from_iida_yaml(CLOS_YAML)

    spine = device_object_id("Spine1")
    leaf_interface = interface_object_id("Leaf1", "GigabitEthernet0/0")
    link = physical_link_object_id(
        InterfaceEndpoint("Spine1", "GigabitEthernet0/0"),
        InterfaceEndpoint("Leaf1", "GigabitEthernet0/0"),
    )

    assert topology.device_object("Spine1") == spine
    assert topology.interface_object("Leaf1", "GigabitEthernet0/0") == leaf_interface
    assert topology.physical_link_for_interface("Leaf1", "GigabitEthernet0/0") == link
    assert topology.graph.nodes[spine]["node_monitor_enabled"] is True
    assert topology.graph.nodes[spine]["role"] == "spine"


def test_clos_causal_topology_supports_reverse_lookup():
    topology = CausalTopology.load_from_iida_yaml(CLOS_YAML)

    assert topology.resolve_device_by_address("10.2.11.1") == "Spine2"
    assert topology.resolve_device_by_address("10.0.0.11") == "Leaf1"
    assert topology.bgp_session_for_devices("Spine1", "Leaf1") == bgp_session_object_id("Spine1-Leaf1-eBGP")
    assert topology.bgp_session_for_devices("Leaf2", "Leaf1") == bgp_session_object_id("Leaf1-Leaf2-iBGP")


def test_clos_physical_link_affects_backed_bgp_session():
    topology = CausalTopology.load_from_iida_yaml(CLOS_YAML)
    link = topology.physical_link_for_interface("Leaf1", "GigabitEthernet0/0")
    session = topology.bgp_session_for_devices("Spine1", "Leaf1")

    assert link is not None
    assert session is not None
    assert topology.graph.has_edge(link, session)
    assert topology.graph[link][session]["relation"] == "link-affects-session"


def test_causal_topology_requires_physical_connection_interface_ids():
    data = {
        "network-model": {
            "physical-layer": {
                "device": [{"device-id": "Spine1"}, {"device-id": "Leaf1"}],
                "physical-connection": [{
                    "connection-id": "bad-link",
                    "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf1"}],
                }],
            }
        }
    }

    with pytest.raises(ValueError, match="requires device-id and interface-id"):
        CausalTopology.from_iida_topology(data)


def test_causal_topology_rejects_unknown_physical_interfaces():
    data = {
        "network-model": {
            "physical-layer": {
                "device": [
                    {"device-id": "Spine1", "interface": [{"interface-id": "Gi0/0"}]},
                    {"device-id": "Leaf1", "interface": [{"interface-id": "Gi0/0"}]},
                ],
                "physical-connection": [{
                    "connection-id": "bad-link",
                    "endpoint": [
                        {"device-id": "Spine1", "interface-id": "Gi0/1"},
                        {"device-id": "Leaf1", "interface-id": "Gi0/0"},
                    ],
                }],
            }
        }
    }

    with pytest.raises(ValueError, match="unknown interface Spine1:Gi0/1"):
        CausalTopology.from_iida_topology(data)