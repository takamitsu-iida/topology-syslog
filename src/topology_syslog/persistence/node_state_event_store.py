"""node-monitor webhook の受信済み event_id を永続化する。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool


class _Base(DeclarativeBase):
    pass


class _NodeStateEventRow(_Base):
    __tablename__ = "node_state_events"

    event_id = Column(String, primary_key=True)
    received_at = Column(DateTime, nullable=False)
    node_id = Column(String, nullable=True, index=True)
    observed_at = Column(DateTime, nullable=True)


def _engine(database_url: str):
    kwargs: dict = {}
    if "sqlite" in database_url:
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
    return create_engine(database_url, **kwargs)


class NodeStateEventStore:
    def __init__(self, database_url: str) -> None:
        self._engine = _engine(database_url)
        _Base.metadata.create_all(self._engine)
        self._migrate()

    def _migrate(self) -> None:
        with self._engine.connect() as connection:
            for ddl in (
                "ALTER TABLE node_state_events ADD COLUMN node_id TEXT",
                "ALTER TABLE node_state_events ADD COLUMN observed_at TIMESTAMP",
            ):
                try:
                    connection.execute(text(ddl))
                    connection.commit()
                except Exception:
                    pass

    def record_if_new(self, event_id: str) -> bool:
        with Session(self._engine) as session:
            if session.get(_NodeStateEventRow, event_id) is not None:
                return False
            session.add(_NodeStateEventRow(
                event_id=event_id,
                received_at=datetime.now(tz=timezone.utc).replace(tzinfo=None),
            ))
            session.commit()
            return True

    def record_event(self, event_id: str, node_id: str, observed_at: datetime) -> str:
        """イベントを記録し、NEW/DUPLICATE/STALE を返す。"""
        with Session(self._engine) as session:
            if session.get(_NodeStateEventRow, event_id) is not None:
                return "DUPLICATE"
            latest = session.query(_NodeStateEventRow).filter(
                _NodeStateEventRow.node_id == node_id,
            ).order_by(_NodeStateEventRow.observed_at.desc()).first()
            observed_naive = observed_at.astimezone(timezone.utc).replace(tzinfo=None)
            result = "STALE" if latest and latest.observed_at and observed_naive < latest.observed_at else "NEW"
            session.add(_NodeStateEventRow(
                event_id=event_id,
                received_at=datetime.now(tz=timezone.utc).replace(tzinfo=None),
                node_id=node_id,
                observed_at=observed_naive,
            ))
            session.commit()
            return result