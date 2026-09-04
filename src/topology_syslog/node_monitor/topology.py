"""トポロジー定義からノード監視先を解決する。"""
from __future__ import annotations

from topology_syslog.topology.graph_engine import GraphEngine


def resolve_monitor_targets(graph: GraphEngine) -> dict[str, str]:
    """監視有効ノードの管理用 Loopback を優先してプローブ先を返す。"""
    targets: dict[str, str] = {}
    for node_id in graph.nodes:
        attrs = graph.get_node_attrs(node_id)
        if not attrs.get("node_monitor_enabled", False):
            continue
        address = attrs.get("loopback")
        if address is None:
            addresses = attrs.get("addresses", set())
            address = next(iter(sorted(addresses)), None)
        if address is not None:
            targets[node_id] = address
    return targets