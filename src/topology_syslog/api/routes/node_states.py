"""node-monitor 状態を frontend へ安全に中継する API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/node-states", tags=["node-monitor"])


@router.get("")
def list_node_states(request: Request) -> list[dict]:
    reader = request.app.state.node_state_reader
    graph = request.app.state.graph
    if reader is None:
        raise HTTPException(status_code=503, detail="Node monitor is not configured")
    if graph is None:
        raise HTTPException(status_code=503, detail="Topology is not loaded")
    return [_serialize(record) for record in reader.get_many(graph.nodes)]


def _serialize(record) -> dict:
    return {
        "node_id": record.node_id,
        "state": record.state.value,
        "observed_at": record.observed_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "reason": record.reason,
        "probes": [
            {"probe_type": probe.probe_type, "target": probe.target, "success": probe.success,
             "observed_at": probe.observed_at.isoformat(), "latency_ms": probe.latency_ms, "error": probe.error}
            for probe in record.probes
        ],
    }