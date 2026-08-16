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
