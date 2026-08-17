"""SQLAlchemy ベースのインシデント永続化ストア。

開発時は SQLite、本番では PostgreSQL へ移行可能。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, create_engine, desc, select, text
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

from topology_syslog.models import Incident


class _Base(DeclarativeBase):
    pass


class _IncidentRow(_Base):
    __tablename__ = "incidents"

    incident_id     = Column(String,   primary_key=True)
    created_at      = Column(DateTime, nullable=False)  # UTC tz-naive で保存
    root_cause      = Column(String,   nullable=False)
    primary_event   = Column(Text,     nullable=False)
    secondary_nodes = Column(JSON,     nullable=False)
    raw_log_count   = Column(Integer,  nullable=False)
    raw_logs        = Column(JSON,     nullable=False, server_default="[]")
    status          = Column(String,   nullable=False)


def _make_engine(database_url: str):
    if "sqlite" in database_url:
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
        return create_engine(database_url, **kwargs)
    return create_engine(database_url)


def _to_row(inc: Incident) -> _IncidentRow:
    return _IncidentRow(
        incident_id=inc.incident_id,
        created_at=inc.created_at.replace(tzinfo=None),  # tz を剥がして保存
        root_cause=inc.root_cause_node,
        primary_event=inc.primary_event,
        secondary_nodes=inc.secondary_nodes,
        raw_log_count=inc.raw_log_count,
        raw_logs=inc.raw_logs,
        status=inc.status,
    )


def _from_row(row: _IncidentRow) -> Incident:
    return Incident(
        incident_id=row.incident_id,
        created_at=row.created_at.replace(tzinfo=timezone.utc),
        root_cause_node=row.root_cause,
        primary_event=row.primary_event,
        secondary_nodes=list(row.secondary_nodes or []),
        raw_log_count=row.raw_log_count,
        raw_logs=list(row.raw_logs or []),
        status=row.status,
    )


class IncidentStore:
    def __init__(self, database_url: str) -> None:
        self._engine = _make_engine(database_url)
        _Base.metadata.create_all(self._engine)
        self._migrate()

    def _migrate(self) -> None:
        # 既存DBへのカラム追加（冪等）
        with self._engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE incidents ADD COLUMN raw_logs JSON"))
                conn.commit()
            except Exception:
                pass

    def save(self, incident: Incident) -> None:
        with Session(self._engine) as session:
            session.merge(_to_row(incident))
            session.commit()

    def get_by_id(self, incident_id: str) -> Incident | None:
        with Session(self._engine) as session:
            row = session.get(_IncidentRow, incident_id)
            return _from_row(row) if row else None

    def list_incidents(
        self,
        status: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> list[Incident]:
        with Session(self._engine) as session:
            stmt = select(_IncidentRow)
            if status:
                stmt = stmt.where(_IncidentRow.status == status)
            if from_dt:
                stmt = stmt.where(_IncidentRow.created_at >= from_dt.replace(tzinfo=None))
            if to_dt:
                stmt = stmt.where(_IncidentRow.created_at <= to_dt.replace(tzinfo=None))
            stmt = stmt.order_by(desc(_IncidentRow.created_at))
            return [_from_row(r) for r in session.scalars(stmt).all()]

    def resolve(self, incident_id: str) -> bool:
        with Session(self._engine) as session:
            row = session.get(_IncidentRow, incident_id)
            if row is None:
                return False
            row.status = "RESOLVED"
            session.commit()
            return True

    def count(self) -> int:
        with Session(self._engine) as session:
            return session.query(_IncidentRow).count()
