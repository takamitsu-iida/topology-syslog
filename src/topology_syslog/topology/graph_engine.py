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

    def update_graph(self, new_graph: nx.DiGraph) -> None:
        self._graph = new_graph

    def node_exists(self, node_id: str) -> bool:
        return node_id in self._graph

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
