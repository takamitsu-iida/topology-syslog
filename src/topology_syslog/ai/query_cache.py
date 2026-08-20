"""インシデントフィンガープリントベースの AI クエリキャッシュ（SQLite）。

キャッシュキー = root_cause_node + Cisco IOS イベント種別 + secondary_nodes の SHA-256。
同ノード×同イベント種別なら詳細メッセージが異なっても同一と見なし LLM 再問い合わせを省く。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

# Cisco IOS の %FAC-SEV-MNEM を抽出する正規表現
_CISCO_RE = re.compile(r'%[A-Z_]+-\d+-[A-Z_]+')


def _normalize_event(primary_event: str) -> str:
    m = _CISCO_RE.search(primary_event)
    return m.group(0) if m else ""


def make_fingerprint(root_cause: str, primary_event: str, secondary_nodes: list[str]) -> str:
    key = json.dumps(
        {"rc": root_cause, "et": _normalize_event(primary_event), "sn": sorted(secondary_nodes)},
        sort_keys=True,
    )
    return hashlib.sha256(key.encode()).hexdigest()


class _Base(DeclarativeBase):
    pass


class _CacheRow(_Base):
    __tablename__ = "ai_cache"
    fingerprint = Column(String,   primary_key=True)
    report      = Column(Text,     nullable=False)
    created_at  = Column(DateTime, nullable=False)


def _make_engine(database_url: str):
    if "sqlite" in database_url:
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
        return create_engine(database_url, **kwargs)
    return create_engine(database_url)


class QueryCache:
    def __init__(self, database_url: str, ttl_days: int = 7) -> None:
        self._engine = _make_engine(database_url)
        _Base.metadata.create_all(self._engine)
        self._ttl = timedelta(days=ttl_days)

    def get(self, root_cause: str, primary_event: str, secondary_nodes: list[str]) -> str | None:
        fp = make_fingerprint(root_cause, primary_event, secondary_nodes)
        cutoff = (datetime.now(tz=timezone.utc) - self._ttl).replace(tzinfo=None)
        with Session(self._engine) as session:
            row = session.get(_CacheRow, fp)
            if row and row.created_at >= cutoff:
                return row.report
        return None

    def set(self, root_cause: str, primary_event: str, secondary_nodes: list[str], report: str) -> None:
        fp = make_fingerprint(root_cause, primary_event, secondary_nodes)
        with Session(self._engine) as session:
            session.merge(_CacheRow(
                fingerprint=fp,
                report=report,
                created_at=datetime.now(tz=timezone.utc).replace(tzinfo=None),
            ))
            session.commit()

    def purge_expired(self) -> int:
        """TTL 切れのキャッシュ行を削除して削除件数を返す。"""
        cutoff = (datetime.now(tz=timezone.utc) - self._ttl).replace(tzinfo=None)
        with Session(self._engine) as session:
            rows = session.scalars(select(_CacheRow).where(_CacheRow.created_at < cutoff)).all()
            count = len(rows)
            for row in rows:
                session.delete(row)
            session.commit()
        return count
