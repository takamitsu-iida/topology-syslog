"""インシデント管理エンドポイント。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from topology_syslog.api.schemas import IncidentListOut, IncidentOut, RCAEvaluationOut, RCAHistoryOut
from topology_syslog.persistence.incident_store import IncidentStore

router = APIRouter(tags=["incidents"])


def _get_store(request: Request) -> IncidentStore:
    return request.app.state.store


@router.get("/incidents", response_model=IncidentListOut)
def list_incidents(
    status: str | None = None,
    condition: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    store: IncidentStore = Depends(_get_store),
) -> IncidentListOut:
    incidents = store.list_incidents(status=status, condition=condition, from_dt=from_dt, to_dt=to_dt)
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


@router.get("/incidents/{incident_id}/rca-history", response_model=RCAHistoryOut)
def get_rca_history(
    incident_id: str,
    limit: int = 20,
    store: IncidentStore = Depends(_get_store),
) -> RCAHistoryOut:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    if store.get_by_id(incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    history = store.list_rca_history(incident_id, limit=limit)
    return RCAHistoryOut(
        evaluations=[RCAEvaluationOut.model_validate(record) for record in history],
        total=len(history),
    )


@router.put("/incidents/{incident_id}/resolve", response_model=IncidentOut)
def resolve_incident(
    incident_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    store: IncidentStore = Depends(_get_store),
) -> IncidentOut:
    if not store.resolve(incident_id):
        raise HTTPException(status_code=404, detail="Incident not found")
    inc = store.get_by_id(incident_id)
    vigil_notifier = getattr(request.app.state, "vigil_notifier", None)
    if vigil_notifier is not None and inc is not None:
        background_tasks.add_task(vigil_notifier.resolve_by_source, inc.root_cause_node)
    return IncidentOut.model_validate(inc)
