"""NetworkX DiGraph のラッパー。グラフ操作の窓口を提供する。"""
from __future__ import annotations

import networkx as nx


class GraphEngine:
    def __init__(self, graph: nx.DiGraph) -> None:
        self._graph = graph

    def get_ancestors(self, node_id: str) -> set[str]:
        return nx.ancestors(self._graph, node_id)

    def get_descendants(self, node_id: str) -> set[str]:
        return nx.descendants(self._graph, node_id)

    def get_ancestors_filtered(self, node_id: str, bgp_nodes: frozenset[str]) -> set[str]:
        """祖先を返す。BGP エッジは宛先ノードが bgp_nodes にある場合のみ辿る。"""
        G = self._graph
        if node_id not in G:
            return set()
        result: set[str] = set()
        stack = [node_id]
        seen = {node_id}
        while stack:
            current = stack.pop()
            for pred in G.predecessors(current):
                if pred in seen:
                    continue
                if G[pred][current].get("edge_type", "physical") == "bgp" and current not in bgp_nodes:
                    continue
                seen.add(pred)
                result.add(pred)
                stack.append(pred)
        return result

    def get_descendants_filtered(self, node_id: str, bgp_nodes: frozenset[str]) -> set[str]:
        """子孫を返す。BGP エッジは宛先ノードが bgp_nodes にある場合のみ辿る。"""
        G = self._graph
        if node_id not in G:
            return set()
        result: set[str] = set()
        stack = [node_id]
        seen = {node_id}
        while stack:
            current = stack.pop()
            for succ in G.successors(current):
                if succ in seen:
                    continue
                if G[current][succ].get("edge_type", "physical") == "bgp" and succ not in bgp_nodes:
                    continue
                seen.add(succ)
                result.add(succ)
                stack.append(succ)
        return result

    def update_graph(self, new_graph: nx.DiGraph) -> None:
        self._graph = new_graph

    def node_exists(self, node_id: str) -> bool:
        return node_id in self._graph

    def get_node_attrs(self, node_id: str) -> dict:
        return dict(self._graph.nodes.get(node_id, {}))

    def get_direct_neighbors(self, node_id: str) -> list[str]:
        """直接隣接ノード（上流・下流を問わず）を返す。"""
        preds = list(self._graph.predecessors(node_id))
        succs = list(self._graph.successors(node_id))
        return list(dict.fromkeys(preds + succs))  # 順序を保ちつつ重複除去

    def find_node_by_address(self, address: str) -> str | None:
        """管理・インターフェース IP アドレスに対応するノードを返す。"""
        for node, attrs in self._graph.nodes(data=True):
            if address in attrs.get("addresses", set()):
                return node
        return None

    @property
    def nodes(self) -> list[str]:
        return list(self._graph.nodes)

    @property
    def edges(self) -> list[tuple[str, str]]:
        return list(self._graph.edges)

    def nodes_with_data(self) -> list[dict[str, str]]:
        return [
            {"id": n, "role": self._graph.nodes[n].get("role", "other")}
            for n in self._graph.nodes
        ]

    def edges_with_data(self) -> list[dict]:
        return [
            {
                "source": s,
                "target": t,
                "edge_type": d.get("edge_type", "physical"),
            }
            for s, t, d in self._graph.edges(data=True)
        ]
