"""SQLAlchemy ベースのインシデント永続化ストア。

開発時は SQLite、本番では PostgreSQL へ移行可能。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, create_engine, desc, select, text
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

from topology_syslog.models import Incident, RCAEvidence, RCAEvaluationRecord, RCAExplanation, RCACandidate

_RAW_LOGS_CAP = 200  # DB に保存するログ最大件数


class _Base(DeclarativeBase):
    pass


class _IncidentRow(_Base):
    __tablename__ = "incidents"

    incident_id       = Column(String,   primary_key=True)
    created_at        = Column(DateTime, nullable=False)  # UTC tz-naive で保存
    root_cause        = Column(String,   nullable=False)
    primary_event     = Column(Text,     nullable=False)
    secondary_nodes   = Column(JSON,     nullable=False)
    raw_log_count     = Column(Integer,  nullable=False)
    raw_logs          = Column(JSON,     nullable=False, server_default="[]")
    status               = Column(String,   nullable=False)
    condition            = Column(String,   nullable=False, server_default="'ACTIVE'")
    recurrence_count     = Column(Integer,  nullable=False, server_default="0")
    maintenance_plan_id  = Column(String,   nullable=True)
    last_fault_at        = Column(DateTime, nullable=True)
    last_recovery_at     = Column(DateTime, nullable=True)
    flap_count           = Column(Integer,  nullable=False, server_default="0")
    recovery_evidence    = Column(JSON,     nullable=False, server_default="[]")
    rca_explanation      = Column(JSON,     nullable=False, server_default="{}")


class _RCAEvaluationRow(_Base):
    __tablename__ = "rca_evaluations"

    evaluation_id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(String, nullable=False, index=True)
    evaluated_at = Column(DateTime, nullable=False)
    reason = Column(String, nullable=False)
    explanation = Column(JSON, nullable=False)


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
        raw_logs=inc.raw_logs[:_RAW_LOGS_CAP],
        status=inc.status,
        condition=inc.condition,
        recurrence_count=inc.recurrence_count,
        maintenance_plan_id=inc.maintenance_plan_id,
        last_fault_at=inc.last_fault_at.replace(tzinfo=None) if inc.last_fault_at else None,
        last_recovery_at=inc.last_recovery_at.replace(tzinfo=None) if inc.last_recovery_at else None,
        flap_count=inc.flap_count,
        recovery_evidence=inc.recovery_evidence,
        rca_explanation=_rca_to_json(inc.rca_explanation),
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
        condition=row.condition or "ACTIVE",
        recurrence_count=int(row.recurrence_count or 0),
        maintenance_plan_id=row.maintenance_plan_id,
        last_fault_at=row.last_fault_at.replace(tzinfo=timezone.utc) if row.last_fault_at else None,
        last_recovery_at=row.last_recovery_at.replace(tzinfo=timezone.utc) if row.last_recovery_at else None,
        flap_count=int(row.flap_count or 0),
        recovery_evidence=list(row.recovery_evidence or []),
        rca_explanation=_rca_from_json(dict(row.rca_explanation or {})),
    )


class IncidentStore:
    def __init__(self, database_url: str) -> None:
        self._engine = _make_engine(database_url)
        _Base.metadata.create_all(self._engine)
        self._migrate()

    def _migrate(self) -> None:
        # 既存DBへのカラム追加（冪等）
        with self._engine.connect() as conn:
            for ddl in [
                "ALTER TABLE incidents ADD COLUMN raw_logs JSON",
                "ALTER TABLE incidents ADD COLUMN recurrence_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE incidents ADD COLUMN condition TEXT NOT NULL DEFAULT 'ACTIVE'",
                "ALTER TABLE incidents ADD COLUMN maintenance_plan_id TEXT",
                "ALTER TABLE incidents ADD COLUMN last_fault_at TIMESTAMP",
                "ALTER TABLE incidents ADD COLUMN last_recovery_at TIMESTAMP",
                "ALTER TABLE incidents ADD COLUMN flap_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE incidents ADD COLUMN recovery_evidence JSON DEFAULT '[]'",
                "ALTER TABLE incidents ADD COLUMN rca_explanation JSON DEFAULT '{}'",
            ]:
                try:
                    conn.execute(text(ddl))
                    conn.commit()
                except Exception:
                    pass

    def save(self, incident: Incident) -> None:
        with Session(self._engine) as session:
            session.merge(_to_row(incident))
            session.commit()

    def update(self, incident: Incident) -> bool:
        """既存インシデントを更新する。存在しない ID は作成しない。"""
        with Session(self._engine) as session:
            row = session.get(_IncidentRow, incident.incident_id)
            if row is None:
                return False
            row.created_at = incident.created_at.replace(tzinfo=None)
            row.root_cause = incident.root_cause_node
            row.primary_event = incident.primary_event
            row.secondary_nodes = incident.secondary_nodes
            row.raw_log_count = incident.raw_log_count
            row.raw_logs = incident.raw_logs[:_RAW_LOGS_CAP]
            row.status = incident.status
            row.condition = incident.condition
            row.recurrence_count = incident.recurrence_count
            row.maintenance_plan_id = incident.maintenance_plan_id
            row.last_fault_at = incident.last_fault_at.replace(tzinfo=None) if incident.last_fault_at else None
            row.last_recovery_at = incident.last_recovery_at.replace(tzinfo=None) if incident.last_recovery_at else None
            row.flap_count = incident.flap_count
            row.recovery_evidence = incident.recovery_evidence
            row.rca_explanation = _rca_to_json(incident.rca_explanation)
            session.commit()
            return True

    def record_rca_evaluation(
        self,
        incident_id: str,
        explanation: RCAExplanation,
        *,
        reason: str = "re-evaluated",
        evaluated_at: datetime | None = None,
    ) -> RCAEvaluationRecord | None:
        with Session(self._engine) as session:
            incident = session.get(_IncidentRow, incident_id)
            if incident is None:
                return None
            incident.rca_explanation = _rca_to_json(explanation)
            row = _RCAEvaluationRow(
                incident_id=incident_id,
                evaluated_at=(evaluated_at or datetime.now(tz=timezone.utc)).replace(tzinfo=None),
                reason=reason,
                explanation=_rca_to_json(explanation),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _rca_evaluation_from_row(row)

    def list_rca_history(self, incident_id: str, limit: int = 20) -> list[RCAEvaluationRecord]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_RCAEvaluationRow)
                .where(_RCAEvaluationRow.incident_id == incident_id)
                .order_by(desc(_RCAEvaluationRow.evaluated_at), desc(_RCAEvaluationRow.evaluation_id))
                .limit(limit)
            ).all()
            return [_rca_evaluation_from_row(row) for row in rows]

    def get_by_id(self, incident_id: str) -> Incident | None:
        with Session(self._engine) as session:
            row = session.get(_IncidentRow, incident_id)
            return _from_row(row) if row else None

    def list_incidents(
        self,
        status: str | None = None,
        condition: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> list[Incident]:
        with Session(self._engine) as session:
            stmt = select(_IncidentRow)
            if status:
                stmt = stmt.where(_IncidentRow.status == status)
            if condition:
                stmt = stmt.where(_IncidentRow.condition == condition)
            if from_dt:
                stmt = stmt.where(_IncidentRow.created_at >= from_dt.replace(tzinfo=None))
            if to_dt:
                stmt = stmt.where(_IncidentRow.created_at <= to_dt.replace(tzinfo=None))
            stmt = stmt.order_by(desc(_IncidentRow.created_at))
            return [_from_row(r) for r in session.scalars(stmt).all()]

    def list_open_active(self) -> list[Incident]:
        """即時推論の統合候補になる OPEN かつ未復旧のインシデントを返す。"""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_IncidentRow)
                .where(_IncidentRow.status == "OPEN")
                .where(_IncidentRow.condition.in_(["ACTIVE", "FLAPPING"]))
                .order_by(desc(_IncidentRow.created_at))
            ).all()
            return [_from_row(r) for r in rows]

    def list_open_lifecycle(self) -> list[Incident]:
        """状態遷移中を含め、再発・復旧判定の候補になる OPEN インシデントを返す。"""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_IncidentRow)
                .where(_IncidentRow.status == "OPEN")
                .where(_IncidentRow.condition.in_(["ACTIVE", "DEGRADED", "RECOVERING", "RECOVERED", "FLAPPING"]))
                .order_by(desc(_IncidentRow.created_at))
            ).all()
            return [_from_row(r) for r in rows]

    def resolve(self, incident_id: str) -> bool:
        """オペレーターによるインシデントのクローズ（status = CLOSED）。"""
        with Session(self._engine) as session:
            row = session.get(_IncidentRow, incident_id)
            if row is None:
                return False
            row.status = "CLOSED"
            session.commit()
            return True

    def recover_by_root_cause(self, root_cause_node: str) -> list[str]:
        """復旧イベント到着時に、指定根本原因ノードのOPENインシデントのconditionをRECOVEREDに更新してIDリストを返す。"""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_IncidentRow)
                .where(_IncidentRow.root_cause == root_cause_node)
                .where(_IncidentRow.status == "OPEN")
                .where(_IncidentRow.condition.in_(["ACTIVE", "FLAPPING"]))
            ).all()
            ids = [r.incident_id for r in rows]
            for row in rows:
                row.condition = "RECOVERED"
            session.commit()
            return ids

    def count(self) -> int:
        with Session(self._engine) as session:
            return session.query(_IncidentRow).count()

    def count_by_root_cause(self, root_cause_node: str) -> int:
        """指定根本原因ノードの既存インシデント件数を返す（再発判定に使用）。"""
        with Session(self._engine) as session:
            return (
                session.query(_IncidentRow)
                .filter(_IncidentRow.root_cause == root_cause_node)
                .filter(_IncidentRow.status == "OPEN")
                .count()
            )

    def find_similar_by_root_cause(self, incident: Incident, n: int = 5) -> list[Incident]:
        """同じ根本原因ノードの過去インシデントを返す（自身は除外）。"""
        with Session(self._engine) as session:
            stmt = (
                select(_IncidentRow)
                .where(_IncidentRow.root_cause == incident.root_cause_node)
                .where(_IncidentRow.incident_id != incident.incident_id)
                .order_by(desc(_IncidentRow.created_at))
                .limit(n)
            )
            return [_from_row(r) for r in session.scalars(stmt).all()]

    def get_by_ids(self, ids: list[str]) -> list[Incident]:
        """複数 ID を一括取得。存在しない ID はスキップ。"""
        if not ids:
            return []
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_IncidentRow).where(_IncidentRow.incident_id.in_(ids))
            ).all()
            by_id = {r.incident_id: _from_row(r) for r in rows}
            return [by_id[i] for i in ids if i in by_id]

    def purge_old_closed(self, days: int = 90) -> int:
        """CLOSED かつ days 日以上前のインシデントを削除して削除件数を返す。"""
        from datetime import timedelta
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_IncidentRow)
                .where(_IncidentRow.status == "CLOSED")
                .where(_IncidentRow.created_at < cutoff)
            ).all()
            count = len(rows)
            for row in rows:
                session.delete(row)
            session.commit()
        return count


def _evidence_to_json(evidence: RCAEvidence) -> dict:
    return {
        "source": evidence.source,
        "summary": evidence.summary,
        "weight": evidence.weight,
        "related_nodes": evidence.related_nodes,
        "related_log_ids": evidence.related_log_ids,
    }


def _candidate_to_json(candidate: RCACandidate | None) -> dict | None:
    if candidate is None:
        return None
    return {
        "node_id": candidate.node_id,
        "confidence": candidate.confidence,
        "evidences": [_evidence_to_json(evidence) for evidence in candidate.evidences],
        "secondary_nodes": candidate.secondary_nodes,
        "alternative_reason": candidate.alternative_reason,
    }


def _rca_to_json(explanation: RCAExplanation) -> dict:
    return {
        "confidence": explanation.confidence,
        "primary_candidate": _candidate_to_json(explanation.primary_candidate),
        "alternative_candidates": [
            candidate for candidate in (_candidate_to_json(item) for item in explanation.alternative_candidates)
            if candidate is not None
        ],
    }


def _evidence_from_json(raw: dict) -> RCAEvidence:
    return RCAEvidence(
        source=str(raw.get("source", "unknown")),
        summary=str(raw.get("summary", "")),
        weight=float(raw.get("weight", 0.0)),
        related_nodes=list(raw.get("related_nodes") or []),
        related_log_ids=list(raw.get("related_log_ids") or []),
    )


def _candidate_from_json(raw: dict | None) -> RCACandidate | None:
    if not raw:
        return None
    return RCACandidate(
        node_id=str(raw.get("node_id", "")),
        confidence=float(raw.get("confidence", 0.0)),
        evidences=[_evidence_from_json(item) for item in raw.get("evidences") or []],
        secondary_nodes=list(raw.get("secondary_nodes") or []),
        alternative_reason=raw.get("alternative_reason"),
    )


def _rca_from_json(raw: dict) -> RCAExplanation:
    return RCAExplanation(
        confidence=raw.get("confidence"),
        primary_candidate=_candidate_from_json(raw.get("primary_candidate")),
        alternative_candidates=[
            candidate for candidate in (_candidate_from_json(item) for item in raw.get("alternative_candidates") or [])
            if candidate is not None
        ],
    )


def _rca_evaluation_from_row(row: _RCAEvaluationRow) -> RCAEvaluationRecord:
    return RCAEvaluationRecord(
        evaluation_id=int(row.evaluation_id),
        incident_id=row.incident_id,
        evaluated_at=row.evaluated_at.replace(tzinfo=timezone.utc),
        reason=row.reason,
        explanation=_rca_from_json(dict(row.explanation or {})),
    )
