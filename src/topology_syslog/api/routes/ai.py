"""AI レポート生成エンドポイント。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["ai"])
_logger = logging.getLogger(__name__)


class ReportOut(BaseModel):
    incident_id: str
    report: str


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
