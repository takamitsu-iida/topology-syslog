"""AI レポート生成エンドポイント。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["ai"])
_logger = logging.getLogger(__name__)


class ReportOut(BaseModel):
    incident_id: str
    report: str


class SimilarIncidentItem(BaseModel):
    incident_id: str
    root_cause_node: str
    created_at: datetime
    primary_event: str
    status: str


class SimilarOut(BaseModel):
    incidents: list[SimilarIncidentItem]
    source: str  # "rag" | "db"


@router.post("/incidents/{incident_id}/report", response_model=ReportOut)
async def generate_report(incident_id: str, request: Request) -> ReportOut:
    """指定インシデントの AI レポートを生成（またはキャッシュから取得）する。

    AI_ENABLED=true かつ LLM が設定されていない場合は 503 を返す。
    """
    generator = getattr(request.app.state, "report_generator", None)
    if generator is None:
        raise HTTPException(
            status_code=503,
            detail="AI report generator not available — set AI_ENABLED=true and configure LLM_PROVIDER",
        )

    incident = await asyncio.to_thread(request.app.state.store.get_by_id, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        report = await asyncio.to_thread(generator.generate, incident)
    except Exception as exc:
        _logger.exception("LLM error for incident %s", incident_id)
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}") from exc

    return ReportOut(incident_id=incident_id, report=report)


@router.get("/incidents/{incident_id}/similar", response_model=SimilarOut)
async def get_similar_incidents(incident_id: str, request: Request) -> SimilarOut:
    """意味的に類似した過去インシデントを返す。AI 無効時は同一根本原因ノードで代替。"""
    incident = await asyncio.to_thread(request.app.state.store.get_by_id, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    def _to_item(inc) -> SimilarIncidentItem:
        return SimilarIncidentItem(
            incident_id=inc.incident_id,
            root_cause_node=inc.root_cause_node,
            created_at=inc.created_at,
            primary_event=inc.primary_event,
            status=inc.status,
        )

    rag_store = getattr(request.app.state, "rag_store", None)
    if rag_store is not None:
        ids = await asyncio.to_thread(rag_store.search_similar_ids, incident)
        incs = await asyncio.to_thread(request.app.state.store.get_by_ids, ids)
        return SimilarOut(incidents=[_to_item(i) for i in incs], source="rag")

    similar = await asyncio.to_thread(
        request.app.state.store.find_similar_by_root_cause, incident
    )
    return SimilarOut(incidents=[_to_item(s) for s in similar], source="db")
