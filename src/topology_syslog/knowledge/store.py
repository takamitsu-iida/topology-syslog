"""Git 管理する SKB YAML のロードと変更検知。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_VALID_STATUSES = frozenset({"approved", "pending", "disabled"})
_VALID_SEVERITY_ACTIONS = frozenset({
    "page_immediately", "create_incident", "correlate_only", "retain_only",
})


@dataclass(frozen=True)
class KnowledgeRule:
    rule_id: str
    signature: str
    description: str | None = None
    vendor: str | None = None
    classification: str | None = None
    correlation_role: str | None = None
    severity_policy: dict[str, str] = field(default_factory=dict)
    dedup_window_sec: int | None = None
    runbook: tuple[str, ...] = ()
    status: str = "pending"
    confidence: float | None = None
    priority: int = 0


class KnowledgeStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._mtimes: dict[Path, int] = {}
        self._rules: list[KnowledgeRule] = []
        self.reload()

    @property
    def rules(self) -> tuple[KnowledgeRule, ...]:
        return tuple(self._rules)

    def reload_if_changed(self) -> bool:
        current = self._file_mtimes()
        if current == self._mtimes:
            return False
        self.reload()
        return True

    def reload(self) -> None:
        rules: list[KnowledgeRule] = []
        for file_path in self._yaml_files():
            with file_path.open(encoding="utf-8") as stream:
                raw = yaml.safe_load(stream) or []
            entries = raw.get("rules", []) if isinstance(raw, dict) and "rules" in raw else raw
            if not isinstance(entries, list):
                raise ValueError(f"SKB file {file_path} must contain a rule or a list of rules")
            rules.extend(_parse_rule(entry, file_path) for entry in entries)
        self._rules = rules
        self._mtimes = self._file_mtimes()

    def get_rule(self, rule_id: str) -> KnowledgeRule | None:
        self.reload_if_changed()
        return next((rule for rule in self._rules if rule.rule_id == rule_id), None)

    def save_rule(self, rule: KnowledgeRule) -> KnowledgeRule:
        """ルールを Git 管理対象の YAML に保存する。既存 ID は置き換える。"""
        target = self._writable_file()
        existing = [current for current in self._rules if current.rule_id != rule.rule_id]
        existing.append(rule)
        raw = {"rules": [_rule_to_raw(current) for current in existing]}
        with target.open("w", encoding="utf-8") as stream:
            yaml.safe_dump(raw, stream, allow_unicode=True, sort_keys=False)
        self.reload()
        return rule

    def _yaml_files(self) -> list[Path]:
        if self._path.is_file():
            return [self._path]
        if not self._path.exists():
            return []
        return sorted((*self._path.glob("*.yaml"), *self._path.glob("*.yml")))

    def _file_mtimes(self) -> dict[Path, int]:
        return {path: path.stat().st_mtime_ns for path in self._yaml_files()}

    def _writable_file(self) -> Path:
        if self._path.is_file() or self._path.suffix in {".yaml", ".yml"}:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            return self._path
        self._path.mkdir(parents=True, exist_ok=True)
        return self._path / "rules.yaml"


def _parse_rule(raw: object, file_path: Path) -> KnowledgeRule:
    if not isinstance(raw, dict):
        raise ValueError(f"SKB rule in {file_path} must be a mapping")
    rule_id = raw.get("id")
    signature = raw.get("signature")
    status = raw.get("status", "pending")
    if not isinstance(rule_id, str) or not rule_id or not isinstance(signature, str) or not signature:
        raise ValueError(f"SKB rule in {file_path} requires non-empty id and signature")
    if status not in _VALID_STATUSES:
        raise ValueError(f"SKB rule {rule_id} has invalid status: {status}")
    severity_policy = raw.get("severity_policy", {})
    runbook = raw.get("runbook", [])
    if not isinstance(severity_policy, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in severity_policy.items()):
        raise ValueError(f"SKB rule {rule_id} has invalid severity_policy")
    for severity_range, action in severity_policy.items():
        if not _is_valid_severity_range(severity_range) or action not in _VALID_SEVERITY_ACTIONS:
            raise ValueError(f"SKB rule {rule_id} has invalid severity policy: {severity_range}={action}")
    if not isinstance(runbook, list) or not all(isinstance(item, str) for item in runbook):
        raise ValueError(f"SKB rule {rule_id} has invalid runbook")
    return KnowledgeRule(
        rule_id=rule_id,
        signature=signature,
        description=raw.get("description"),
        vendor=raw.get("vendor"),
        classification=raw.get("classification"),
        correlation_role=raw.get("correlation_role"),
        severity_policy=severity_policy,
        dedup_window_sec=raw.get("dedup_window_sec"),
        runbook=tuple(runbook),
        status=status,
        confidence=raw.get("confidence"),
        priority=raw.get("priority", 0),
    )


def _is_valid_severity_range(value: str) -> bool:
    try:
        parts = value.split("-", maxsplit=1)
        if len(parts) == 1:
            return 0 <= int(parts[0]) <= 7
        start, end = (int(part) for part in parts)
        return 0 <= start <= end <= 7
    except ValueError:
        return False


def _rule_to_raw(rule: KnowledgeRule) -> dict:
    raw = {
        "id": rule.rule_id,
        "signature": rule.signature,
        "status": rule.status,
        "priority": rule.priority,
    }
    for key, value in {
        "description": rule.description,
        "vendor": rule.vendor,
        "classification": rule.classification,
        "correlation_role": rule.correlation_role,
        "severity_policy": rule.severity_policy or None,
        "dedup_window_sec": rule.dedup_window_sec,
        "runbook": list(rule.runbook) or None,
        "confidence": rule.confidence,
    }.items():
        if value is not None:
            raw[key] = value
    return raw