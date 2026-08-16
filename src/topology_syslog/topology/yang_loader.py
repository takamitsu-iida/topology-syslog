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
    physical = data["network-model"]["physical-layer"]
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
        # 優先度が低い (= より上流) 側から高い側へエッジを張る
        if role_of.get(a, 5) <= role_of.get(b, 5):
            G.add_edge(a, b)
        else:
            G.add_edge(b, a)

    return G
