from pathlib import Path

from topology_syslog.node_monitor.topology import resolve_monitor_targets
from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader


_ROOT = Path(__file__).parent.parent.parent
CLOS_YAML = str(_ROOT / "configs" / "clos" / "yang_topology.yaml")


def test_clos_monitor_targets_use_loopback_addresses():
    graph = GraphEngine(TopologyLoader().load_from_iida_yaml(CLOS_YAML))

    targets = resolve_monitor_targets(graph)

    assert targets == {
        "Spine1": "10.0.0.1",
        "Spine2": "10.0.0.2",
        "Leaf1": "10.0.0.11",
        "Leaf2": "10.0.0.12",
        "Leaf3": "10.0.0.13",
    }


def test_monitor_target_falls_back_to_interface_address_without_loopback():
    graph = GraphEngine(TopologyLoader().load_from_dict({
        "network-model": {"physical-layer": {"device": [{
            "device-id": "Leaf1", "role": "leaf",
            "node-monitor-enabled": True,
            "interface": [{"ip-address": "192.0.2.10/24"}],
        }]}},
    }))

    assert resolve_monitor_targets(graph) == {"Leaf1": "192.0.2.10"}


def test_monitor_targets_exclude_nodes_without_explicit_enablement():
    graph = GraphEngine(TopologyLoader().load_from_dict({
        "network-model": {"physical-layer": {"device": [
            {"device-id": "Spine1", "role": "spine", "loopback": "10.0.0.1/32", "node-monitor-enabled": True},
            {"device-id": "Leaf1", "role": "leaf", "loopback": "10.0.0.11/32"},
        ]}},
    }))

    assert resolve_monitor_targets(graph) == {"Spine1": "10.0.0.1"}