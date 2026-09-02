"""RCA explanation のルールベース confidence スコアリング。"""
from __future__ import annotations

from topology_syslog.models import RCAEvidence, RCAExplanation, SyslogMessage


def score_rca_explanation(
    explanation: RCAExplanation,
    messages: list[SyslogMessage],
) -> RCAExplanation:
    if explanation.primary_candidate is None:
        explanation.confidence = None
        return explanation

    candidate = explanation.primary_candidate
    weights = [_score_evidence(evidence, messages) for evidence in candidate.evidences]
    for evidence, weight in zip(candidate.evidences, weights, strict=False):
        evidence.weight = weight

    confidence = min(1.0, round(sum(weights), 2))
    candidate.confidence = confidence
    explanation.confidence = confidence

    for alternative in explanation.alternative_candidates:
        alternative.confidence = _score_alternative(alternative.node_id, candidate.node_id, messages)
    explanation.alternative_candidates.sort(key=lambda item: item.confidence, reverse=True)
    return explanation


def _score_evidence(evidence: RCAEvidence, messages: list[SyslogMessage]) -> float:
    summary = evidence.summary.lower()
    if evidence.source == "syslog" and "root-cause candidate" in summary:
        return 0.30
    if evidence.source == "syslog" and "repeated matching events" in summary:
        return 0.35
    if evidence.source == "topology" and "common upstream ancestor" in summary:
        return 0.25
    if evidence.source == "topology" and "downstream" in summary:
        return 0.20
    if evidence.source == "topology" and "no logged upstream" in summary:
        return 0.15
    if evidence.source == "skb":
        return min(0.15, max((msg.knowledge_confidence or 0.0 for msg in messages), default=0.0) * 0.15)
    if evidence.source == "maintenance":
        return 0.05
    if evidence.source == "investigation":
        return 0.15
    return 0.0


def _score_alternative(node_id: str, selected_root: str, messages: list[SyslogMessage]) -> float:
    base = 0.10 if any(message.hostname == node_id for message in messages) else 0.0
    if node_id != selected_root:
        base += 0.05
    return round(min(base, 0.30), 2)