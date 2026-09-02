"""SYSLOG Knowledge Base の観測データ参照エンドポイント。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from topology_syslog.api.schemas import (
    IncidentOut,
    KnowledgeRuleCreate,
    KnowledgeRuleOut,
    KnowledgeAuditOut,
    SimilarKnowledgeOut,
    UnknownEventListOut,
    UnknownEventOut,
)
from topology_syslog.knowledge.store import KnowledgeRule, KnowledgeStore
from topology_syslog.persistence.unknown_event_store import UnknownEventStore
from topology_syslog.persistence.knowledge_audit_store import KnowledgeAuditStore

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _get_unknown_event_store(request: Request) -> UnknownEventStore:
    store = request.app.state.unknown_event_store
    if store is None:
        raise HTTPException(status_code=503, detail="SYSLOG Knowledge Base is not configured")
    return store


def _get_knowledge_store(request: Request) -> KnowledgeStore:
    matcher = request.app.state.knowledge_matcher
    if matcher is None:
        raise HTTPException(status_code=503, detail="SYSLOG Knowledge Base is not configured")
    return matcher.store


def _get_audit_store(request: Request) -> KnowledgeAuditStore:
    store = request.app.state.knowledge_audit_store
    if store is None:
        raise HTTPException(status_code=503, detail="SYSLOG Knowledge Base is not configured")
    return store


def _actor(request: Request) -> str | None:
    return request.headers.get("X-Actor")


@router.get("/rules", response_model=list[KnowledgeRuleOut])
def list_rules(request: Request) -> list[KnowledgeRuleOut]:
    store = _get_knowledge_store(request)
    store.reload_if_changed()
    return [KnowledgeRuleOut.model_validate(rule) for rule in store.rules]


@router.post("/rules", response_model=KnowledgeRuleOut, status_code=201)
def create_rule(payload: KnowledgeRuleCreate, request: Request) -> KnowledgeRuleOut:
    store = _get_knowledge_store(request)
    if store.get_rule(payload.rule_id) is not None:
        raise HTTPException(status_code=409, detail="Knowledge rule already exists")
    try:
        rule = KnowledgeRule(
            rule_id=payload.rule_id,
            signature=payload.signature,
            description=payload.description,
            vendor=payload.vendor,
            classification=payload.classification,
            correlation_role=payload.correlation_role,
            severity_policy=payload.severity_policy,
            dedup_window_sec=payload.dedup_window_sec,
            runbook=tuple(payload.runbook),
            confidence=payload.confidence,
            priority=payload.priority,
        )
        saved = store.save_rule(rule)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _get_audit_store(request).record_rule_change("created", saved, _actor(request))
    return KnowledgeRuleOut.model_validate(saved)


@router.put("/rules/{rule_id}", response_model=KnowledgeRuleOut)
def update_rule(rule_id: str, payload: KnowledgeRuleCreate, request: Request) -> KnowledgeRuleOut:
    if payload.rule_id != rule_id:
        raise HTTPException(status_code=422, detail="rule_id must match path")
    store = _get_knowledge_store(request)
    existing = store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Knowledge rule not found")
    updated = KnowledgeRule(
        rule_id=payload.rule_id, signature=payload.signature, description=payload.description, vendor=payload.vendor,
        classification=payload.classification, correlation_role=payload.correlation_role,
        severity_policy=payload.severity_policy, dedup_window_sec=payload.dedup_window_sec,
        runbook=tuple(payload.runbook), status=existing.status,
        confidence=payload.confidence, priority=payload.priority,
    )
    saved = store.save_rule(updated)
    _get_audit_store(request).record_rule_change("updated", saved, _actor(request))
    return KnowledgeRuleOut.model_validate(saved)


@router.post("/rules/{rule_id}/approve", response_model=KnowledgeRuleOut)
def approve_rule(rule_id: str, request: Request) -> KnowledgeRuleOut:
    return _set_rule_status(rule_id, "approved", request)


@router.post("/rules/{rule_id}/disable", response_model=KnowledgeRuleOut)
def disable_rule(rule_id: str, request: Request) -> KnowledgeRuleOut:
    return _set_rule_status(rule_id, "disabled", request)


def _set_rule_status(rule_id: str, status: str, request: Request) -> KnowledgeRuleOut:
    store = _get_knowledge_store(request)
    rule = store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Knowledge rule not found")
    saved = store.save_rule(KnowledgeRule(
        rule_id=rule.rule_id, signature=rule.signature, description=rule.description, vendor=rule.vendor,
        classification=rule.classification, correlation_role=rule.correlation_role,
        severity_policy=rule.severity_policy, dedup_window_sec=rule.dedup_window_sec,
        runbook=rule.runbook, status=status, confidence=rule.confidence, priority=rule.priority,
    ))
    _get_audit_store(request).record_rule_change(status, saved, _actor(request))
    return KnowledgeRuleOut.model_validate(saved)


@router.post("/rules/{rule_id}/rollback/{version}", response_model=KnowledgeRuleOut)
def rollback_rule(rule_id: str, version: int, request: Request) -> KnowledgeRuleOut:
    audit_store = _get_audit_store(request)
    previous = audit_store.get_rule_version(rule_id, version)
    if previous is None:
        raise HTTPException(status_code=404, detail="Knowledge rule version not found")
    saved = _get_knowledge_store(request).save_rule(previous)
    audit_store.record_rule_change("rolled_back", saved, _actor(request))
    return KnowledgeRuleOut.model_validate(saved)


@router.get("/audit", response_model=list[KnowledgeAuditOut])
def list_audit_events(request: Request, rule_id: str | None = None, limit: int = 100) -> list[KnowledgeAuditOut]:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return [KnowledgeAuditOut(**event) for event in _get_audit_store(request).list_events(rule_id, limit)]


@router.get("/unknown-events", response_model=UnknownEventListOut)
def list_unknown_events(request: Request, limit: int = 100) -> UnknownEventListOut:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    events = _get_unknown_event_store(request).list_events(limit=limit)
    return UnknownEventListOut(
        events=[UnknownEventOut.model_validate(event) for event in events],
        total=len(events),
    )


@router.get("/unknown-events/{signature}", response_model=UnknownEventOut)
def get_unknown_event(signature: str, request: Request) -> UnknownEventOut:
    event = _get_unknown_event_store(request).get(signature)
    if event is None:
        raise HTTPException(status_code=404, detail="Unknown event not found")
    return UnknownEventOut.model_validate(event)


@router.get("/unknown-events/{signature}/suggestions", response_model=SimilarKnowledgeOut)
def get_unknown_event_suggestions(signature: str, request: Request) -> SimilarKnowledgeOut:
    event = _get_unknown_event_store(request).get(signature)
    if event is None:
        raise HTTPException(status_code=404, detail="Unknown event not found")
    rag_store = getattr(request.app.state, "rag_store", None)
    if rag_store is not None:
        ids = rag_store.search_similar_text_ids(event.representative_message)
        incidents = request.app.state.store.get_by_ids(ids)
        source = "rag"
    else:
        incidents = request.app.state.store.list_incidents()[:5]
        source = "recent"
    return SimilarKnowledgeOut(
        incidents=[IncidentOut.model_validate(incident) for incident in incidents], source=source
    )