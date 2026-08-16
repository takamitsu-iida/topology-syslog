"""インシデント管理エンドポイント。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from topology_syslog.api.schemas import IncidentListOut, IncidentOut
from topology_syslog.persistence.incident_store import IncidentStore

router = APIRouter(tags=["incidents"])


def _get_store(request: Request) -> IncidentStore:
    return request.app.state.store


@router.get("/incidents", response_model=IncidentListOut)
def list_incidents(
    status: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    store: IncidentStore = Depends(_get_store),
) -> IncidentListOut:
    incidents = store.list_incidents(status=status, from_dt=from_dt, to_dt=to_dt)
    return IncidentListOut(
        incidents=[IncidentOut.model_validate(i) for i in incidents],
        total=len(incidents),
    )


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: str,
    store: IncidentStore = Depends(_get_store),
) -> IncidentOut:
    inc = store.get_by_id(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentOut.model_validate(inc)


@router.put("/incidents/{incident_id}/resolve", response_model=IncidentOut)
def resolve_incident(
    incident_id: str,
    store: IncidentStore = Depends(_get_store),
) -> IncidentOut:
    if not store.resolve(incident_id):
        raise HTTPException(status_code=404, detail="Incident not found")
    inc = store.get_by_id(incident_id)
    return IncidentOut.model_validate(inc)
