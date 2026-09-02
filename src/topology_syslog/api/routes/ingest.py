"""シスログ受信 + 根本原因推論 + ストア保存 + WebSocket ブロードキャストを一括処理する。

Vector などの送信元からのシスログ行を受け取り、インシデントを生成する。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from topology_syslog.api.schemas import IncidentOut
from topology_syslog.ingestion.syslog_parser import parse
from topology_syslog.knowledge.classifier import can_create_new_incident, should_skip_inference

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
    """シスログメッセージを受け取り、インシデントを生成して WebSocket へブロードキャストする。"""
    graph = request.app.state.graph
    if graph is None:
        raise HTTPException(status_code=503, detail="Topology not loaded")

    syslog_msgs = [parse(m.raw.encode(), m.source_ip) for m in payload.messages]

    matcher = request.app.state.knowledge_matcher
    classification_enforced = matcher is not None
    classified_messages = []
    if matcher is not None:
        unknown_event_store = request.app.state.unknown_event_store
        for msg in syslog_msgs:
            rule = matcher.classify(msg)
            result = request.app.state.event_classifier.classify(msg, rule)
            if msg.knowledge_status == "unknown":
                await asyncio.to_thread(unknown_event_store.record, msg)
            classified_messages.append((msg, result))
    else:
        for msg in syslog_msgs:
            classified_messages.append((msg, request.app.state.event_classifier.classify(msg, None)))

    classified_messages = [
        (msg, result) for msg, result in classified_messages
        if not should_skip_inference(result)
    ]
    for msg in syslog_msgs:
        await asyncio.to_thread(request.app.state.raw_log_store.record, msg)
    syslog_msgs = [msg for msg, _ in classified_messages]

    # 旧 SYSLOG_IGNORE_FILE と装置別 severity フィルターを互換のため適用
    syslog_filter = request.app.state.syslog_filter
    syslog_msgs = [m for m in syslog_msgs if not syslog_filter.is_ignored(m)]

    inferencer = request.app.state.inferencer
    incidents = inferencer.infer(syslog_msgs, graph)

    store = request.app.state.store
    ws_manager = request.app.state.ws_manager
    created_incidents = []
    for inc in incidents:
        related_nodes = {inc.root_cause_node, *inc.secondary_nodes}
        related_results = [result for msg, result in classified_messages if msg.hostname in related_nodes]
        can_create = any(
            can_create_new_incident(result, enforce=classification_enforced)
            for result in related_results
        )
        if not can_create:
            continue
        await asyncio.to_thread(store.save, inc)
        created_incidents.append(inc)
        await ws_manager.broadcast({
            "type": "incident.new",
            "incident": IncidentOut.model_validate(inc).model_dump(mode="json"),
        })

    return [IncidentOut.model_validate(i) for i in created_incidents]
