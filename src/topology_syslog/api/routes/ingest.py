"""シスログ受信 + 根本原因推論 + ストア保存 + WebSocket ブロードキャストを一括処理する。

Vector などの送信元からのシスログ行を受け取り、インシデントを生成する。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from topology_syslog.api.schemas import IncidentOut
from topology_syslog.ingestion.syslog_parser import parse

router = APIRouter(tags=["ingest"])


@router.get("/debug/status")
async def debug_status(request: Request) -> dict:
    """pipeline の状態を返す。問題切り分け用。"""
    return {
        "topology_loaded": request.app.state.graph is not None,
        "syslog_port": getattr(request.app.state, "syslog_port", None),
        "syslog_recv_count": getattr(request.app.state, "syslog_recv_count", 0),
        "incident_count": request.app.state.store.count(),
    }


class RawMessage(BaseModel):
    source_ip: str = "127.0.0.1"
    raw: str  # RFC 3164 / RFC 5424 形式のシスログ文字列


class IngestRequest(BaseModel):
    messages: list[RawMessage]


@router.post("/ingest", response_model=list[IncidentOut])
async def ingest_syslog(request: Request, payload: IngestRequest) -> list[IncidentOut]:
    """UDP 受信と同じ即時パイプラインで SYSLOG を処理する。"""
    graph = request.app.state.graph
    if graph is None:
        raise HTTPException(status_code=503, detail="Topology not loaded")

    from topology_syslog.api.main import _process_message_immediately

    messages = sorted(
        (parse(message.raw.encode(), message.source_ip) for message in payload.messages),
        key=lambda message: message.received_at,
    )
    affected: dict[str, object] = {}
    for message in messages:
        for incident in await _process_message_immediately(request.app, message):
            affected[incident.incident_id] = incident

    return [IncidentOut.model_validate(incident) for incident in affected.values()]
