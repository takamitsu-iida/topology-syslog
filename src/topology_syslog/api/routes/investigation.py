"""インシデント調査エンドポイント。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["investigation"])
_logger = logging.getLogger(__name__)


class InvestigationStartOut(BaseModel):
    incident_id: str
    status: str


class CommandResultOut(BaseModel):
    device_id: str
    command: str
    output: str
    timestamp: datetime
    error: str | None


class InvestigationReportOut(BaseModel):
    incident_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    summary: str
    error: str | None
    commands: list[CommandResultOut]


def _agent(request: Request):
    agent = getattr(request.app.state, "investigation_agent", None)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "調査機能が無効です — "
                "INVESTIGATION_ENABLED=true かつ DEVICE_CREDENTIALS を設定してください"
            ),
        )
    return agent


@router.post("/incidents/{incident_id}/investigation", response_model=InvestigationStartOut)
async def start_investigation(incident_id: str, request: Request) -> InvestigationStartOut:
    """指定インシデントの装置調査をバックグラウンドで開始する。"""
    agent = _agent(request)

    incident = await asyncio.to_thread(request.app.state.store.get_by_id, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    investigations: dict = request.app.state.investigations
    existing = investigations.get(incident_id)
    if existing and existing.status == "running":
        raise HTTPException(status_code=409, detail="調査が既に実行中です")

    from topology_syslog.investigation.models import InvestigationReport
    placeholder = InvestigationReport(
        incident_id=incident_id,
        started_at=datetime.now(tz=incident.created_at.tzinfo),
        status="running",
    )
    investigations[incident_id] = placeholder

    async def _run() -> None:
        report = await agent.investigate(incident)
        investigations[incident_id] = report
        await request.app.state.ws_manager.broadcast({
            "type": "investigation.done",
            "incident_id": incident_id,
            "status": report.status,
        })

    asyncio.create_task(_run())
    return InvestigationStartOut(incident_id=incident_id, status="running")


@router.get("/incidents/{incident_id}/investigation", response_model=InvestigationReportOut)
async def get_investigation(incident_id: str, request: Request) -> InvestigationReportOut:
    """指定インシデントの調査状況・結果を返す。"""
    _agent(request)  # 機能有効チェック

    report = request.app.state.investigations.get(incident_id)
    if report is None:
        raise HTTPException(status_code=404, detail="調査結果が見つかりません")

    return InvestigationReportOut(
        incident_id=report.incident_id,
        status=report.status,
        started_at=report.started_at,
        completed_at=report.completed_at,
        summary=report.summary,
        error=report.error,
        commands=[
            CommandResultOut(
                device_id=r.device_id,
                command=r.command,
                output=r.output,
                timestamp=r.timestamp,
                error=r.error,
            )
            for r in report.command_results
        ],
    )
