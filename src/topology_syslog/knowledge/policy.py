"""SKB ルールに定義された Severity 別の処理方針。"""
from __future__ import annotations

from enum import StrEnum

from topology_syslog.knowledge.store import KnowledgeRule


class SeverityAction(StrEnum):
    PAGE_IMMEDIATELY = "page_immediately"
    CREATE_INCIDENT = "create_incident"
    CORRELATE_ONLY = "correlate_only"
    RETAIN_ONLY = "retain_only"


def resolve_severity_action(rule: KnowledgeRule | None, severity: int) -> SeverityAction | None:
    """ルールの Severity 範囲に一致するアクションを返す。未定義時は既存動作を維持する。"""
    if rule is None:
        return None
    for severity_range, action in rule.severity_policy.items():
        if _matches_severity_range(severity_range, severity):
            return SeverityAction(action)
    return None


def _matches_severity_range(severity_range: str, severity: int) -> bool:
    try:
        if "-" not in severity_range:
            return severity == int(severity_range)
        start, end = severity_range.split("-", maxsplit=1)
        return int(start) <= severity <= int(end)
    except ValueError:
        return False