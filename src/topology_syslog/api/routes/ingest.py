"""シスログ受信 + 根本原因推論 + ストア保存 + WebSocket ブロードキャストを一括処理する。

Vector / test_sender.py からのシスログ行を受け取り、インシデントを生成する。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from topology_syslog.api.schemas import IncidentOut
from topology_syslog.ingestion.syslog_parser import parse

router = APIRouter(tags=["ingest"])


class RawMessage(BaseModel):
    source_ip: str = "127.0.0.1"
    raw: str  # RFC 3164 / RFC 5424 形式のシスログ文字列


class IngestRequest(BaseModel):
    messages: list[RawMessage]


@router.post("/ingest", response_model=list[IncidentOut])
async def ingest_syslog(request: Request, payload: IngestRequest) -> list[IncidentOut]:
    """シスログメッセージを受け取り、インシデントを生成して WebSocket へブロードキャストする。"""
    graph = request.app.state.graph
    if graph is None:
        raise HTTPException(status_code=503, detail="Topology not loaded")

    syslog_msgs = [parse(m.raw.encode(), m.source_ip) for m in payload.messages]

    # 無視フィルターを適用
    syslog_filter = request.app.state.syslog_filter
    syslog_msgs = [m for m in syslog_msgs if not syslog_filter.is_ignored(m)]

    inferencer = request.app.state.inferencer
    incidents = inferencer.infer(syslog_msgs, graph)

    store = request.app.state.store
    ws_manager = request.app.state.ws_manager
    for inc in incidents:
        await asyncio.to_thread(store.save, inc)
        await ws_manager.broadcast({
            "type": "incident.new",
            "incident": IncidentOut.model_validate(inc).model_dump(mode="json"),
        })

    return [IncidentOut.model_validate(i) for i in incidents]
