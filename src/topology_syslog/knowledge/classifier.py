"""SKB ルールと Severity から SYSLOG の運用分類を決定する。"""
from __future__ import annotations

from topology_syslog.knowledge.policy import SeverityAction, resolve_severity_action
from topology_syslog.knowledge.store import KnowledgeRule
from topology_syslog.models import (
    ClassificationReason,
    EventAction,
    EventClassification,
    EventClassificationResult,
    SyslogMessage,
)


class EventClassifier:
    def classify(
        self,
        message: SyslogMessage,
        rule: KnowledgeRule | None = None,
    ) -> EventClassificationResult:
        severity_action = resolve_severity_action(rule, message.severity)
        action = _to_event_action(severity_action, rule)
        classification = _to_event_classification(message, rule, action)
        reasons = _build_reasons(rule, severity_action, classification)
        result = EventClassificationResult(
            classification=classification,
            action=action,
            reasons=tuple(reasons),
        )
        message.event_classification = result.classification
        message.event_action = result.action
        message.classification_reasons = list(result.reasons)
        return result


def should_skip_inference(result: EventClassificationResult) -> bool:
    return (
        result.action == EventAction.RETAIN_ONLY
        or result.classification in {EventClassification.NOISE, EventClassification.RETAIN_ONLY}
    )


def can_create_new_incident(result: EventClassificationResult, *, enforce: bool = True) -> bool:
    if not enforce:
        return True
    return (
        result.classification == EventClassification.FAULT_SIGNAL
        and result.action == EventAction.CREATE_INCIDENT
    )


def _to_event_action(
    severity_action: SeverityAction | None,
    rule: KnowledgeRule | None,
) -> EventAction:
    if severity_action in {SeverityAction.PAGE_IMMEDIATELY, SeverityAction.CREATE_INCIDENT}:
        return EventAction.CREATE_INCIDENT
    if severity_action == SeverityAction.CORRELATE_ONLY:
        return EventAction.CORRELATE_ONLY
    if severity_action == SeverityAction.RETAIN_ONLY:
        return EventAction.RETAIN_ONLY
    if rule is None:
        return EventAction.REVIEW
    return EventAction.CREATE_INCIDENT


def _to_event_classification(
    message: SyslogMessage,
    rule: KnowledgeRule | None,
    action: EventAction,
) -> EventClassification:
    if message.is_recovery:
        return EventClassification.RECOVERY
    if rule is None:
        return EventClassification.UNKNOWN
    normalized = _normalize_classification(rule.classification)
    if normalized is not None:
        return normalized
    role = (rule.correlation_role or "").strip().lower()
    if role in {"informational", "retain-only", "retain_only"}:
        return EventClassification.RETAIN_ONLY
    if role in {"root-cause-candidate", "primary", "fault-signal"}:
        return EventClassification.FAULT_SIGNAL
    if role in {"secondary-impact", "correlate-only", "correlate_only"}:
        return EventClassification.STATE_CHANGE
    if action == EventAction.RETAIN_ONLY:
        return EventClassification.RETAIN_ONLY
    if action == EventAction.CREATE_INCIDENT:
        return EventClassification.FAULT_SIGNAL
    if action == EventAction.CORRELATE_ONLY:
        return EventClassification.STATE_CHANGE
    return EventClassification.UNKNOWN


def _normalize_classification(value: str | None) -> EventClassification | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("_", "-")
    direct = {
        item.value: item
        for item in EventClassification
    }
    if normalized in direct:
        return direct[normalized]
    if "security" in normalized or "auth" in normalized or "login" in normalized or "acl" in normalized:
        return EventClassification.SECURITY
    if "config" in normalized or "configuration" in normalized:
        return EventClassification.CONFIG_CHANGE
    if "recover" in normalized or "restored" in normalized or "established" in normalized:
        return EventClassification.RECOVERY
    if "noise" in normalized or "informational" in normalized:
        return EventClassification.NOISE
    if "fault" in normalized or "failure" in normalized or "down" in normalized:
        return EventClassification.FAULT_SIGNAL
    if "state" in normalized or "change" in normalized or "adjacency" in normalized:
        return EventClassification.STATE_CHANGE
    return None


def _build_reasons(
    rule: KnowledgeRule | None,
    severity_action: SeverityAction | None,
    classification: EventClassification,
) -> list[ClassificationReason]:
    reasons: list[ClassificationReason] = []
    if rule is None:
        reasons.append(ClassificationReason(source="skb", detail="no approved SKB rule matched"))
        return reasons
    reasons.append(
        ClassificationReason(
            source="skb",
            detail=f"matched approved rule {rule.rule_id}",
            confidence=rule.confidence,
        )
    )
    if rule.classification:
        reasons.append(
            ClassificationReason(
                source="skb.classification",
                detail=f"{rule.classification} -> {classification.value}",
                confidence=rule.confidence,
            )
        )
    if severity_action is not None:
        reasons.append(
            ClassificationReason(
                source="skb.severity_policy",
                detail=f"severity policy resolved to {severity_action.value}",
                confidence=rule.confidence,
            )
        )
    elif rule.correlation_role:
        reasons.append(
            ClassificationReason(
                source="skb.correlation_role",
                detail=f"correlation role is {rule.correlation_role}",
                confidence=rule.confidence,
            )
        )
    return reasons