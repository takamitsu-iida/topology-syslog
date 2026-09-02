"""SKB ルールの変更・適用履歴を永続化する監査ストア。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, desc, select
from sqlalchemy.orm import Session

from topology_syslog.knowledge.store import KnowledgeRule
from topology_syslog.models import SyslogMessage
from topology_syslog.persistence.incident_store import _Base, _make_engine


class _KnowledgeAuditRow(_Base):
    __tablename__ = "knowledge_audit_events"

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    occurred_at = Column(DateTime, nullable=False)
    event_type = Column(String, nullable=False)
    rule_id = Column(String, nullable=True)
    rule_version = Column(Integer, nullable=True)
    actor = Column(String, nullable=True)
    signature = Column(String, nullable=True)
    details = Column(JSON, nullable=False)


class KnowledgeAuditStore:
    def __init__(self, database_url: str) -> None:
        self._engine = _make_engine(database_url)
        _Base.metadata.create_all(self._engine)

    def record_rule_change(self, action: str, rule: KnowledgeRule, actor: str | None = None) -> int:
        with Session(self._engine) as session:
            version = self._next_version(session, rule.rule_id)
            row = _KnowledgeAuditRow(
                occurred_at=datetime.now(tz=timezone.utc).replace(tzinfo=None),
                event_type=action,
                rule_id=rule.rule_id,
                rule_version=version,
                actor=actor,
                signature=rule.signature,
                details={"rule": _rule_snapshot(rule)},
            )
            session.add(row)
            session.commit()
            return version

    def record_application(self, message: SyslogMessage, rule: KnowledgeRule | None) -> None:
        with Session(self._engine) as session:
            session.add(_KnowledgeAuditRow(
                occurred_at=message.received_at.replace(tzinfo=None),
                event_type="applied" if rule else "unmatched",
                rule_id=rule.rule_id if rule else None,
                rule_version=self._current_version(session, rule.rule_id) if rule else None,
                actor=None,
                signature=message.normalized_signature,
                details={
                    "hostname": message.hostname,
                    "severity": message.severity,
                    "vendor": message.vendor,
                    "knowledge_status": message.knowledge_status,
                },
            ))
            session.commit()

    def list_events(self, rule_id: str | None = None, limit: int = 100) -> list[dict]:
        with Session(self._engine) as session:
            stmt = select(_KnowledgeAuditRow).order_by(desc(_KnowledgeAuditRow.occurred_at)).limit(limit)
            if rule_id:
                stmt = stmt.where(_KnowledgeAuditRow.rule_id == rule_id)
            return [_row_to_dict(row) for row in session.scalars(stmt).all()]

    def get_rule_version(self, rule_id: str, version: int) -> KnowledgeRule | None:
        with Session(self._engine) as session:
            row = session.scalars(
                select(_KnowledgeAuditRow)
                .where(_KnowledgeAuditRow.rule_id == rule_id)
                .where(_KnowledgeAuditRow.rule_version == version)
                .where(_KnowledgeAuditRow.event_type != "applied")
            ).first()
            if row is None:
                return None
            return _rule_from_snapshot(row.details["rule"])

    def _next_version(self, session: Session, rule_id: str) -> int:
        return self._current_version(session, rule_id) + 1

    def _current_version(self, session: Session, rule_id: str) -> int:
        value = session.scalars(
            select(_KnowledgeAuditRow.rule_version)
            .where(_KnowledgeAuditRow.rule_id == rule_id)
            .where(_KnowledgeAuditRow.rule_version.is_not(None))
            .order_by(desc(_KnowledgeAuditRow.rule_version))
            .limit(1)
        ).first()
        return int(value or 0)


def _rule_snapshot(rule: KnowledgeRule) -> dict:
    return {
        "rule_id": rule.rule_id, "signature": rule.signature, "description": rule.description, "vendor": rule.vendor,
        "classification": rule.classification, "correlation_role": rule.correlation_role,
        "severity_policy": rule.severity_policy, "dedup_window_sec": rule.dedup_window_sec,
        "runbook": list(rule.runbook), "status": rule.status,
        "confidence": rule.confidence, "priority": rule.priority,
    }


def _rule_from_snapshot(raw: dict) -> KnowledgeRule:
    return KnowledgeRule(**{**raw, "runbook": tuple(raw["runbook"])})


def _row_to_dict(row: _KnowledgeAuditRow) -> dict:
    return {
        "event_id": row.event_id, "occurred_at": row.occurred_at.replace(tzinfo=timezone.utc),
        "event_type": row.event_type, "rule_id": row.rule_id, "rule_version": row.rule_version,
        "actor": row.actor, "signature": row.signature, "details": dict(row.details or {}),
    }