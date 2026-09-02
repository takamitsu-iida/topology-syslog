"""分類済み Raw SYSLOG の検索エンドポイント。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from topology_syslog.api.schemas import RawLogListOut, RawLogOut

router = APIRouter(prefix="/raw-logs", tags=["raw-logs"])


@router.get("", response_model=RawLogListOut)
def list_raw_logs(
    request: Request,
    limit: int = 100,
    hostname: str | None = None,
    classification: str | None = None,
    action: str | None = None,
    knowledge_status: str | None = None,
) -> RawLogListOut:
    if not 1 <= limit <= 500:
        limit = 100
    logs = request.app.state.raw_log_store.list_logs(
        limit=limit,
        hostname=hostname,
        classification=classification,
        action=action,
        knowledge_status=knowledge_status,
    )
    return RawLogListOut(logs=[RawLogOut.model_validate(log) for log in logs], total=len(logs))