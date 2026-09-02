"""承認済み SKB ルールを SYSLOG メッセージへ付与する。"""
from __future__ import annotations

from fnmatch import fnmatchcase

from topology_syslog.knowledge.store import KnowledgeRule, KnowledgeStore
from topology_syslog.models import SyslogMessage
from topology_syslog.persistence.knowledge_audit_store import KnowledgeAuditStore


class KnowledgeMatcher:
    def __init__(self, store: KnowledgeStore, audit_store: KnowledgeAuditStore | None = None) -> None:
        self._store = store
        self._audit_store = audit_store

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    def classify(self, message: SyslogMessage) -> KnowledgeRule | None:
        self._store.reload_if_changed()
        signature = message.normalized_signature
        if not signature:
            return None
        matches = [
            rule for rule in self._store.rules
            if rule.status == "approved"
            and (rule.vendor is None or rule.vendor == message.vendor)
            and fnmatchcase(signature, rule.signature)
        ]
        if not matches:
            message.knowledge_status = "unknown"
            message.knowledge_id = None
            message.recommended_action = None
            message.knowledge_confidence = None
            if self._audit_store is not None:
                self._audit_store.record_application(message, None)
            return None
        rule = max(matches, key=lambda item: (item.priority, len(item.signature)))
        message.knowledge_status = "known"
        message.knowledge_id = rule.rule_id
        message.recommended_action = "; ".join(rule.runbook) or None
        message.knowledge_confidence = rule.confidence
        if self._audit_store is not None:
            self._audit_store.record_application(message, rule)
        return rule