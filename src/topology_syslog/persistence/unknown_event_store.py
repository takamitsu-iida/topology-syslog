"""未知 SYSLOG イベントを正規化シグネチャ単位で集約するストア。"""
from __future__ import annotations

from datetime import timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, desc, select
from sqlalchemy.orm import Session

from topology_syslog.models import SyslogMessage, UnknownEvent
from topology_syslog.persistence.incident_store import _Base, _make_engine


class _UnknownEventRow(_Base):
    __tablename__ = "unknown_events"

    signature = Column(String, primary_key=True)
    vendor = Column(String, nullable=True)
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    occurrence_count = Column(Integer, nullable=False)
    severity_counts = Column(JSON, nullable=False)
    nodes = Column(JSON, nullable=False)
    representative_message = Column(Text, nullable=False)


class UnknownEventStore:
    def __init__(self, database_url: str) -> None:
        self._engine = _make_engine(database_url)
        _Base.metadata.create_all(self._engine)

    def record(self, message: SyslogMessage) -> UnknownEvent:
        signature = message.normalized_signature or "<unclassified>"
        observed_at = message.received_at.replace(tzinfo=None)
        with Session(self._engine) as session:
            row = session.get(_UnknownEventRow, signature)
            if row is None:
                row = _UnknownEventRow(
                    signature=signature,
                    vendor=message.vendor,
                    first_seen=observed_at,
                    last_seen=observed_at,
                    occurrence_count=1,
                    severity_counts={str(message.severity): 1},
                    nodes=[message.hostname],
                    representative_message=message.message,
                )
                session.add(row)
            else:
                row.last_seen = observed_at
                row.occurrence_count += 1
                counts = dict(row.severity_counts or {})
                key = str(message.severity)
                counts[key] = int(counts.get(key, 0)) + 1
                row.severity_counts = counts
                row.nodes = sorted(set(row.nodes or []) | {message.hostname})
            session.commit()
            return _from_row(row)

    def get(self, signature: str) -> UnknownEvent | None:
        with Session(self._engine) as session:
            row = session.get(_UnknownEventRow, signature)
            return _from_row(row) if row else None

    def list_events(self, limit: int = 100) -> list[UnknownEvent]:
        """最終観測時刻の新しい順に未知イベントを返す。"""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_UnknownEventRow)
                .order_by(desc(_UnknownEventRow.last_seen))
                .limit(limit)
            ).all()
            return [_from_row(row) for row in rows]


def _from_row(row: _UnknownEventRow) -> UnknownEvent:
    return UnknownEvent(
        signature=row.signature,
        vendor=row.vendor,
        first_seen=row.first_seen.replace(tzinfo=timezone.utc),
        last_seen=row.last_seen.replace(tzinfo=timezone.utc),
        occurrence_count=row.occurrence_count,
        severity_counts=dict(row.severity_counts or {}),
        nodes=list(row.nodes or []),
        representative_message=row.representative_message,
    )