"""iida-network-model 形式 (JSON / YAML) → NetworkX DiGraph 変換。"""
from __future__ import annotations

import json

import networkx as nx
import yaml

# デバイスロールの上流優先度 (値が小さいほど上流)
_ROLE_PRIORITY: dict[str, int] = {
    "border":       0,
    "spine":        0,
    "core":         1,
    "distribution": 2,
    "access":       3,
    "leaf":         3,
    "oob":          4,
    "other":        5,
}


class TopologyLoader:
    def load_from_iida_json(self, path: str) -> nx.DiGraph:
        with open(path) as f:
            data = json.load(f)
        return _build_graph(data)

    def load_from_iida_yaml(self, path: str) -> nx.DiGraph:
        with open(path) as f:
            data = yaml.safe_load(f)
        return _build_graph(data)

    def load_from_dict(self, data: dict) -> nx.DiGraph:
        return _build_graph(data)


def _build_graph(data: dict) -> nx.DiGraph:
    nm = data["network-model"]
    physical = nm["physical-layer"]
    G: nx.DiGraph = nx.DiGraph()

    role_of: dict[str, int] = {}
    for dev in physical.get("device", []):
        dev_id: str = dev["device-id"]
        role_str: str = dev.get("role", "other")
        role_of[dev_id] = _ROLE_PRIORITY.get(role_str, 5)
        G.add_node(dev_id, role=role_str)

    for conn in physical.get("physical-connection", []):
        eps = conn.get("endpoint", [])
        if len(eps) != 2:
            continue
        a: str = eps[0]["device-id"]
        b: str = eps[1]["device-id"]
        if a not in G or b not in G:
            continue
        if role_of.get(a, 5) <= role_of.get(b, 5):
            G.add_edge(a, b, edge_type="physical")
        else:
            G.add_edge(b, a, edge_type="physical")

    # BGP sessions — physical edges take precedence; only add new edges for BGP-only peers
    l3 = nm.get("layer3-layer", {})
    for session in l3.get("bgp-session", []):
        eps = session.get("endpoint", [])
        if len(eps) != 2:
            continue
        a = eps[0]["device-id"]
        b = eps[1]["device-id"]
        if a not in G or b not in G:
            continue
        bgp_type: str = session.get("type", "ebgp")
        # iBGP: alphabetical order to avoid cycles between same-role peers
        if bgp_type == "ibgp":
            src, dst = sorted([a, b])
        else:
            if role_of.get(a, 5) <= role_of.get(b, 5):
                src, dst = a, b
            else:
                src, dst = b, a
        if not G.has_edge(src, dst):
            G.add_edge(src, dst, edge_type="bgp", bgp_type=bgp_type)

    return G
