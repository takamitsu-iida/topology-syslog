"""シスログ受信 + 根本原因推論 + ストア保存 + WebSocket ブロードキャストを一括処理する。

Vector などの送信元からのシスログ行を受け取り、インシデントを生成する。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from topology_syslog.api.schemas import IncidentOut
from topology_syslog.ingestion.syslog_parser import parse

router = APIRouter(tags=["ingest"])


@router.get("/debug/status")
async def debug_status(request: Request) -> dict:
    """pipeline の状態を返す。問題切り分け用。"""
    return {
        "topology_loaded": request.app.state.graph is not None,
        "causal_topology_loaded": getattr(request.app.state, "causal_topology", None) is not None,
        "rca_engine": getattr(request.app.state, "rca_engine", "legacy"),
        "syslog_port": getattr(request.app.state, "syslog_port", None),
        "syslog_recv_count": getattr(request.app.state, "syslog_recv_count", 0),
        "incident_count": request.app.state.store.count(),
        "last_rca_comparison": getattr(request.app.state, "last_rca_comparison", None),
        "last_rca_migration_readiness": getattr(request.app.state, "last_rca_migration_readiness", None),
    }


class RawMessage(BaseModel):
    source_ip: str = "127.0.0.1"
    raw: str  # RFC 3164 / RFC 5424 形式のシスログ文字列


class IngestRequest(BaseModel):
    messages: list[RawMessage]


class LabeledRCAExample(BaseModel):
    sample_id: str
    expected_root_cause_object: str
    expected_legacy_nodes: list[str] = []
    messages: list[RawMessage]


class RCAMigrationEvaluateRequest(BaseModel):
    samples: list[LabeledRCAExample]
    min_accuracy: float = 0.8
    min_confidence: float = 0.6


@router.post("/debug/rca/hypothesis")
async def debug_hypothesis_rca(request: Request, payload: IngestRequest) -> dict:
    """legacy と hypothesis RCA の比較結果を返す。保存・通知は行わない。"""
    graph = request.app.state.graph
    if graph is None:
        raise HTTPException(status_code=503, detail="Topology not loaded")
    if getattr(request.app.state, "hypothesis_engine", None) is None:
        raise HTTPException(status_code=503, detail="Hypothesis RCA engine not available")

    from topology_syslog.api.main import _compare_rca_engines

    messages = _parse_and_classify(request, payload.messages)

    comparison = _compare_rca_engines(request.app, messages)
    request.app.state.last_rca_comparison = comparison
    return comparison


@router.post("/debug/rca/migration-readiness")
async def debug_rca_migration_readiness(request: Request, payload: RCAMigrationEvaluateRequest) -> dict:
    """ラベル付きサンプルで legacy / hypothesis の移行可否を評価する。"""
    if request.app.state.graph is None:
        raise HTTPException(status_code=503, detail="Topology not loaded")
    if getattr(request.app.state, "hypothesis_engine", None) is None:
        raise HTTPException(status_code=503, detail="Hypothesis RCA engine not available")

    from topology_syslog.api.main import _compare_rca_engines
    from topology_syslog.correlation.rca_migration import RCASampleEvaluation, evaluate_migration_readiness, readiness_to_dict

    evaluations: list[RCASampleEvaluation] = []
    for sample in payload.samples:
        messages = _parse_and_classify(request, sample.messages)
        comparison = _compare_rca_engines(request.app, messages)
        hypothesis_root = comparison["hypothesis"]["root_cause_object"]
        legacy_roots = tuple(comparison["legacy"]["root_cause_nodes"])
        expected_legacy = tuple(sample.expected_legacy_nodes)
        evaluations.append(RCASampleEvaluation(
            sample_id=sample.sample_id,
            expected_root_cause_object=sample.expected_root_cause_object,
            expected_legacy_nodes=expected_legacy,
            legacy_roots=legacy_roots,
            hypothesis_root=hypothesis_root,
            hypothesis_confidence=float(comparison["hypothesis"]["confidence"]),
            legacy_matches_expected=bool(expected_legacy and set(legacy_roots) == set(expected_legacy)),
            hypothesis_matches_expected=hypothesis_root == sample.expected_root_cause_object,
            root_object_type=sample.expected_root_cause_object.split(":", 1)[0],
        ))

    readiness = evaluate_migration_readiness(
        evaluations,
        min_accuracy=payload.min_accuracy,
        min_confidence=payload.min_confidence,
    )
    result = readiness_to_dict(readiness)
    request.app.state.last_rca_migration_readiness = result
    return result


@router.post("/ingest", response_model=list[IncidentOut])
async def ingest_syslog(request: Request, payload: IngestRequest) -> list[IncidentOut]:
    """UDP 受信と同じ即時パイプラインで SYSLOG を処理する。"""
    graph = request.app.state.graph
    if graph is None:
        raise HTTPException(status_code=503, detail="Topology not loaded")

    from topology_syslog.api.main import _process_message_immediately

    messages = sorted(
        (parse(message.raw.encode(), message.source_ip) for message in payload.messages),
        key=lambda message: message.received_at,
    )
    affected: dict[str, object] = {}
    for message in messages:
        for incident in await _process_message_immediately(request.app, message):
            affected[incident.incident_id] = incident

    return [IncidentOut.model_validate(incident) for incident in affected.values()]


def _parse_and_classify(request: Request, raw_messages: list[RawMessage]) -> list:
    messages = sorted(
        (parse(message.raw.encode(), message.source_ip) for message in raw_messages),
        key=lambda message: message.received_at,
    )
    matcher = getattr(request.app.state, "knowledge_matcher", None)
    classifier = request.app.state.event_classifier
    for message in messages:
        rule = matcher.classify(message) if matcher is not None else None
        classifier.classify(message, rule)
    return messages
