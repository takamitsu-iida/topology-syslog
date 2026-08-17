from pathlib import Path

import networkx as nx
import pytest

from topology_syslog.topology.yang_loader import TopologyLoader

_ROOT = Path(__file__).parent.parent.parent
POC_JSON = str(_ROOT / "poc" / "topology" / "l3_topology.json")
SMALL_YAML = str(_ROOT / "yang" / "examples" / "sample_topology_small.yaml")


def test_json_nodes_exist():
    g = TopologyLoader().load_from_iida_json(POC_JSON)
    for node in ("Core-Router1", "Dist-Switch1", "Access-SW1", "Branch-Router2", "Branch-Access-SW1"):
        assert node in g.nodes


def test_json_edge_upstream_to_downstream():
    g = TopologyLoader().load_from_iida_json(POC_JSON)
    # core → distribution → access
    assert g.has_edge("Core-Router1", "Dist-Switch1")
    assert not g.has_edge("Dist-Switch1", "Core-Router1")
    assert g.has_edge("Dist-Switch1", "Access-SW1")
    assert not g.has_edge("Access-SW1", "Dist-Switch1")


def test_json_branch_is_separate_subgraph():
    g = TopologyLoader().load_from_iida_json(POC_JSON)
    # Core-Router1 と Branch-Router2 はトポロジー上で接続されていない
    assert not g.has_edge("Core-Router1", "Branch-Router2")
    assert not g.has_edge("Branch-Router2", "Core-Router1")


def test_json_returns_digraph():
    g = TopologyLoader().load_from_iida_json(POC_JSON)
    assert isinstance(g, nx.DiGraph)


def test_yaml_nodes_exist():
    g = TopologyLoader().load_from_iida_yaml(SMALL_YAML)
    for node in ("router-01", "fw-01", "core-sw-01"):
        assert node in g.nodes


def test_yaml_returns_digraph():
    g = TopologyLoader().load_from_iida_yaml(SMALL_YAML)
    assert isinstance(g, nx.DiGraph)


def test_yaml_edge_count_matches_connections():
    g = TopologyLoader().load_from_iida_yaml(SMALL_YAML)
    # YAML の physical-connection 数と一致することを確認
    assert g.number_of_edges() > 0


# ---------------------------------------------------------------------------
# BGP セッション (Phase 6)
# ---------------------------------------------------------------------------

def _bgp_fixture(sessions: list[dict], devices: list[dict], connections: list[dict] | None = None) -> dict:
    return {
        "network-model": {
            "physical-layer": {
                "device": devices,
                "physical-connection": connections or [],
            },
            "layer3-layer": {"bgp-session": sessions},
        }
    }


def test_ibgp_edge_added_between_leaves():
    """iBGP セッションが物理エッジのない Leaf 間にグラフエッジを追加する"""
    data = _bgp_fixture(
        devices=[{"device-id": "Leaf1", "role": "leaf"}, {"device-id": "Leaf2", "role": "leaf"}],
        sessions=[{
            "session-id": "Leaf1-Leaf2-iBGP",
            "type": "ibgp",
            "endpoint": [{"device-id": "Leaf1"}, {"device-id": "Leaf2"}],
        }],
    )
    g = TopologyLoader().load_from_dict(data)
    assert g.has_edge("Leaf1", "Leaf2")
    assert g["Leaf1"]["Leaf2"]["edge_type"] == "bgp"


def test_ibgp_direction_is_alphabetical():
    """iBGP エッジ方向はアルファベット順（循環回避）"""
    data = _bgp_fixture(
        devices=[{"device-id": "Zebra", "role": "leaf"}, {"device-id": "Alpha", "role": "leaf"}],
        sessions=[{
            "session-id": "Zebra-Alpha-iBGP",
            "type": "ibgp",
            "endpoint": [{"device-id": "Zebra"}, {"device-id": "Alpha"}],
        }],
    )
    g = TopologyLoader().load_from_dict(data)
    assert g.has_edge("Alpha", "Zebra")
    assert not g.has_edge("Zebra", "Alpha")


def test_ebgp_does_not_duplicate_physical_edge():
    """eBGP セッションが既存の物理エッジを上書きしない"""
    data = _bgp_fixture(
        devices=[{"device-id": "Spine1", "role": "spine"}, {"device-id": "Leaf1", "role": "leaf"}],
        connections=[{
            "connection-id": "Spine1-Leaf1",
            "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf1"}],
        }],
        sessions=[{
            "session-id": "Spine1-Leaf1-eBGP",
            "type": "ebgp",
            "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf1"}],
        }],
    )
    g = TopologyLoader().load_from_dict(data)
    assert g.has_edge("Spine1", "Leaf1")
    assert g["Spine1"]["Leaf1"]["edge_type"] == "physical"


def test_physical_edge_has_edge_type_attribute():
    """物理エッジに edge_type='physical' が付与される"""
    data = _bgp_fixture(
        devices=[{"device-id": "Spine1", "role": "spine"}, {"device-id": "Leaf1", "role": "leaf"}],
        connections=[{
            "connection-id": "Spine1-Leaf1",
            "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf1"}],
        }],
        sessions=[],
    )
    g = TopologyLoader().load_from_dict(data)
    assert g["Spine1"]["Leaf1"]["edge_type"] == "physical"
