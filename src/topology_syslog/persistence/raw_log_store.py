"""分類済み SYSLOG を検索・監査用に保存するストア。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, desc, select
from sqlalchemy.orm import Session

from topology_syslog.models import ClassificationReason, RawLogRecord, SyslogMessage
from topology_syslog.persistence.incident_store import _Base, _make_engine


class _RawLogRow(_Base):
    __tablename__ = "raw_syslog_logs"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    received_at = Column(DateTime, nullable=False)
    source_ip = Column(String, nullable=False)
    hostname = Column(String, nullable=False)
    facility = Column(Integer, nullable=False)
    severity = Column(Integer, nullable=False)
    message = Column(Text, nullable=False)
    vendor = Column(String, nullable=True)
    event_type = Column(String, nullable=True)
    normalized_signature = Column(String, nullable=True)
    knowledge_status = Column(String, nullable=False)
    knowledge_id = Column(String, nullable=True)
    event_classification = Column(String, nullable=False)
    event_action = Column(String, nullable=True)
    classification_reasons = Column(JSON, nullable=False)


class RawLogStore:
    def __init__(self, database_url: str) -> None:
        self._engine = _make_engine(database_url)
        _Base.metadata.create_all(self._engine)

    def record(self, message: SyslogMessage) -> RawLogRecord:
        with Session(self._engine) as session:
            row = _RawLogRow(
                received_at=message.received_at.replace(tzinfo=None),
                source_ip=message.source_ip,
                hostname=message.hostname,
                facility=message.facility,
                severity=message.severity,
                message=message.message,
                vendor=message.vendor,
                event_type=message.event_type,
                normalized_signature=message.normalized_signature,
                knowledge_status=message.knowledge_status,
                knowledge_id=message.knowledge_id,
                event_classification=message.event_classification.value,
                event_action=message.event_action.value if message.event_action else None,
                classification_reasons=[_reason_to_dict(reason) for reason in message.classification_reasons],
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _from_row(row)

    def list_logs(
        self,
        *,
        limit: int = 100,
        hostname: str | None = None,
        classification: str | None = None,
        action: str | None = None,
        knowledge_status: str | None = None,
    ) -> list[RawLogRecord]:
        with Session(self._engine) as session:
            stmt = select(_RawLogRow)
            if hostname:
                stmt = stmt.where(_RawLogRow.hostname == hostname)
            if classification:
                stmt = stmt.where(_RawLogRow.event_classification == classification)
            if action:
                stmt = stmt.where(_RawLogRow.event_action == action)
            if knowledge_status:
                stmt = stmt.where(_RawLogRow.knowledge_status == knowledge_status)
            rows = session.scalars(
                stmt.order_by(desc(_RawLogRow.received_at), desc(_RawLogRow.log_id)).limit(limit)
            ).all()
            return [_from_row(row) for row in rows]

    def count(self) -> int:
        with Session(self._engine) as session:
            return len(session.scalars(select(_RawLogRow.log_id)).all())


def _reason_to_dict(reason: ClassificationReason) -> dict[str, object]:
    return {
        "source": reason.source,
        "detail": reason.detail,
        "confidence": reason.confidence,
    }


def _from_row(row: _RawLogRow) -> RawLogRecord:
    received_at: datetime = row.received_at
    return RawLogRecord(
        log_id=int(row.log_id),
        received_at=received_at.replace(tzinfo=timezone.utc),
        source_ip=row.source_ip,
        hostname=row.hostname,
        facility=int(row.facility),
        severity=int(row.severity),
        message=row.message,
        vendor=row.vendor,
        event_type=row.event_type,
        normalized_signature=row.normalized_signature,
        knowledge_status=row.knowledge_status,
        knowledge_id=row.knowledge_id,
        event_classification=row.event_classification,
        event_action=row.event_action,
        classification_reasons=list(row.classification_reasons or []),
    )