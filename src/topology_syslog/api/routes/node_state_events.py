"""node-monitor からの状態変化 webhook。"""
from __future__ import annotations

import asyncio
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, status
from topology_syslog.api.schemas import IncidentOut
from topology_syslog.correlation.confidence import score_rca_explanation
from topology_syslog.models import Incident, RCAEvidence, RCACandidate

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/node-state-events")
async def receive_node_state_event(
    request: Request,
    payload: dict,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    configured_token = request.app.state.node_monitor_event_token
    if not configured_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook is not configured")
    expected = f"Bearer {configured_token}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid node-monitor token")

    event_id = payload.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="event_id is required")
    if payload.get("event_type") != "node_state.changed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported event_type")

    node_id = payload.get("node_id")
    state = payload.get("state")
    if not isinstance(node_id, str) or not node_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="node_id is required")
    if state not in {"UP", "DOWN", "DEGRADED", "UNKNOWN"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported state")

    observed_at = _parse_observed_at(payload.get("observed_at"))
    event_status = request.app.state.node_state_event_store.record_event(event_id, node_id, observed_at)
    if event_status != "NEW":
        return {
            "status": "accepted",
            "duplicate": event_status == "DUPLICATE",
            "stale": event_status == "STALE",
            "event_id": event_id,
            "related_incident_ids": [],
            "updated_incident_ids": [],
        }

    related, match_type = _find_related_incidents(request, node_id, state=state)
    updated = []
    for incident in related:
        if await _apply_state_event(request, incident, payload, observed_at):
            updated.append(incident)
    return {
        "status": "accepted",
        "duplicate": False,
        "stale": False,
        "event_id": event_id,
        "related_incident_ids": [incident.incident_id for incident in related],
        "updated_incident_ids": [incident.incident_id for incident in updated],
        "match_type": match_type,
    }


async def _apply_state_event(
    request: Request,
    incident: Incident,
    payload: dict,
    observed_at: datetime,
) -> bool:
    node_id = payload["node_id"]
    state = payload["state"]
    summary = f"{node_id} is {state.lower()} according to node monitor: {payload.get('reason', '')}"
    explanation = incident.rca_explanation
    candidate = explanation.primary_candidate
    if candidate is None:
        candidate = RCACandidate(
            node_id=incident.root_cause_node,
            confidence=0.0,
            secondary_nodes=list(incident.secondary_nodes),
        )
        explanation.primary_candidate = candidate
    if any(
        evidence.source == "node-monitor" and node_id in evidence.related_nodes
        and state.lower() in evidence.summary.lower()
        for evidence in candidate.evidences
    ):
        return False

    probe_ids = [str(probe.get("probe_type", "unknown")) for probe in payload.get("probes", [])]
    candidate.evidences.append(RCAEvidence(
        source="node-monitor",
        summary=summary,
        weight=0.0,
        related_nodes=[node_id],
        related_log_ids=[payload["event_id"], *probe_ids],
    ))
    score_rca_explanation(explanation, [])
    if state in {"DOWN", "DEGRADED"} and incident.condition == "ACTIVE":
        incident.condition = "DEGRADED"
    elif state == "UP" and incident.condition == "DEGRADED":
        incident.condition = "RECOVERING"
        incident.last_recovery_at = observed_at
        _schedule_recovery(request, incident.incident_id, observed_at)
    request.app.state.store.update(incident)
    request.app.state.store.record_rca_evaluation(
        incident.incident_id,
        explanation,
        reason=f"node-monitor state changed to {state}",
        evaluated_at=observed_at,
    )
    await request.app.state.ws_manager.broadcast({
        "type": "incident.updated",
        "incident": IncidentOut.model_validate(incident).model_dump(mode="json"),
    })
    return True


def _schedule_recovery(request: Request, incident_id: str, observed_at: datetime) -> None:
    tasks = request.app.state.recovery_tasks
    previous = tasks.pop(incident_id, None)
    if previous is not None:
        previous.cancel()
    tasks[incident_id] = asyncio.create_task(
        _complete_recovery(request, incident_id, observed_at)
    )


async def _complete_recovery(request: Request, incident_id: str, observed_at: datetime) -> None:
    try:
        await asyncio.sleep(request.app.state.recovery_quiet_period_sec)
        incident = await asyncio.to_thread(request.app.state.store.get_by_id, incident_id)
        if incident is None or incident.status != "OPEN" or incident.condition != "RECOVERING":
            return
        if incident.last_recovery_at != observed_at:
            return
        incident.condition = "RECOVERED"
        await asyncio.to_thread(request.app.state.store.update, incident)
        await request.app.state.ws_manager.broadcast({
            "type": "incident.recovered",
            "incident_id": incident_id,
            "incident": IncidentOut.model_validate(incident).model_dump(mode="json"),
        })
    except asyncio.CancelledError:
        raise
    finally:
        current = request.app.state.recovery_tasks.get(incident_id)
        if current is asyncio.current_task():
            request.app.state.recovery_tasks.pop(incident_id, None)


def _parse_observed_at(value: object) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


def _find_related_incidents(
    request: Request,
    node_id: str,
    *,
    state: str = "DOWN",
) -> tuple[list[Incident], str]:
    """OPEN インシデントを直接一致、次にトポロジー一致の順で返す。"""
    incidents = (
        request.app.state.store.list_open_lifecycle()
        if state == "UP"
        else request.app.state.store.list_open_active()
    )
    direct_root = [incident for incident in incidents if incident.root_cause_node == node_id]
    if direct_root:
        return direct_root, "root_cause"

    direct_secondary = [
        incident for incident in incidents if node_id in incident.secondary_nodes
    ]
    if direct_secondary:
        return direct_secondary, "secondary_node"

    graph = request.app.state.graph
    if graph is None or not graph.node_exists(node_id):
        return [], "none"

    related: list[Incident] = []
    for incident in incidents:
        related_nodes = {incident.root_cause_node, *incident.secondary_nodes}
        if any(
            node_id in graph.get_ancestors(node) or node_id in graph.get_descendants(node)
            for node in related_nodes
            if graph.node_exists(node)
        ):
            related.append(incident)
    return related, "topology" if related else "none"