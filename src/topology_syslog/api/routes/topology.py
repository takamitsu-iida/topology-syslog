"""トポロジー参照・リロードエンドポイント。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader

router = APIRouter(tags=["topology"])


def _graph(request: Request) -> GraphEngine:
    g = request.app.state.graph
    if g is None:
        raise HTTPException(status_code=503, detail="Topology not loaded")
    return g


@router.get("/topology/nodes")
def get_topology_nodes(request: Request) -> dict:
    graph = _graph(request)
    return {"nodes": graph.nodes_with_data(), "total": len(graph.nodes)}


@router.get("/topology/graph")
def get_topology_graph(request: Request) -> dict:
    graph = _graph(request)
    nodes = [{"data": d} for d in graph.nodes_with_data()]
    edges = [
        {"data": {"id": f"{s}__{t}", "source": s, "target": t}}
        for s, t in graph.edges
    ]
    return {"elements": {"nodes": nodes, "edges": edges}}


@router.post("/topology/reload")
def reload_topology(request: Request) -> dict:
    graph = _graph(request)
    path: str | None = request.app.state.topology_path
    source: str = request.app.state.topology_source
    if path is None:
        raise HTTPException(status_code=503, detail="Topology path not configured")
    loader = TopologyLoader()
    new_g = (
        loader.load_from_iida_json(path)
        if source == "ietf-json"
        else loader.load_from_iida_yaml(path)
    )
    graph.update_graph(new_g)
    return {"status": "reloaded", "nodes": len(new_g.nodes), "edges": len(new_g.edges)}
