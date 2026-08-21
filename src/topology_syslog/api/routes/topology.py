"""トポロジー参照・リロードエンドポイント。"""
from __future__ import annotations

import json

import yaml
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
        {"data": {"id": f"{e['source']}__{e['target']}", **e}}
        for e in graph.edges_with_data()
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
    if source == "ietf-json":
        with open(path) as f:
            raw = json.load(f)
    else:
        with open(path) as f:
            raw = yaml.safe_load(f)
    new_g = loader.load_from_dict(raw)
    graph.update_graph(new_g)
    request.app.state.topology_raw = raw
    return {"status": "reloaded", "nodes": len(new_g.nodes), "edges": len(new_g.edges)}
