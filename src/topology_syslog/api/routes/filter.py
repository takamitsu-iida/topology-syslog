"""シスログフィルターの参照・リロードエンドポイント。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from topology_syslog.ingestion.syslog_filter import SyslogFilter

router = APIRouter(tags=["filter"])


@router.get("/filter/patterns")
def get_filter_patterns(request: Request) -> dict:
    syslog_filter = request.app.state.syslog_filter
    return {
        "patterns": syslog_filter.patterns,
        "count": len(syslog_filter.patterns),
        "ignore_file": request.app.state.ignore_file,
    }


@router.post("/filter/reload")
def reload_filter(request: Request) -> dict:
    ignore_file: str | None = request.app.state.ignore_file
    if ignore_file is None:
        raise HTTPException(status_code=503, detail="No ignore file configured")
    new_filter = SyslogFilter.from_file(ignore_file)
    request.app.state.syslog_filter = new_filter
    return {
        "status": "reloaded",
        "patterns": new_filter.patterns,
        "count": len(new_filter.patterns),
    }
