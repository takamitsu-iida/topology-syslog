"""Persistent storage for device investigation reports."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, JSON, String, Text, select, update
from sqlalchemy.orm import Session

from topology_syslog.investigation.models import CommandResult, InvestigationReport
from topology_syslog.persistence.incident_store import _Base, _make_engine


class _InvestigationRow(_Base):
    __tablename__ = "investigation_reports"

    incident_id = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    summary = Column(Text, nullable=False, server_default="")
    error = Column(Text, nullable=True)
    command_results = Column(JSON, nullable=False, server_default="[]")


class InvestigationStore:
    def __init__(self, database_url: str) -> None:
        self._engine = _make_engine(database_url)
        _Base.metadata.create_all(self._engine)

    def save(self, report: InvestigationReport) -> None:
        with Session(self._engine) as session:
            session.merge(_InvestigationRow(
                incident_id=report.incident_id,
                status=report.status,
                started_at=report.started_at.replace(tzinfo=None),
                completed_at=report.completed_at.replace(tzinfo=None) if report.completed_at else None,
                summary=report.summary,
                error=report.error,
                command_results=[_command_to_dict(result) for result in report.command_results],
            ))
            session.commit()

    def get(self, incident_id: str) -> InvestigationReport | None:
        with Session(self._engine) as session:
            row = session.get(_InvestigationRow, incident_id)
            return _from_row(row) if row else None

    def mark_running_as_interrupted(self) -> int:
        with Session(self._engine) as session:
            result = session.execute(
                update(_InvestigationRow)
                .where(_InvestigationRow.status == "running")
                .values(
                    status="interrupted",
                    completed_at=datetime.now(tz=timezone.utc).replace(tzinfo=None),
                    error="Server restarted before the investigation completed.",
                )
            )
            session.commit()
            return int(result.rowcount or 0)


def _command_to_dict(result: CommandResult) -> dict:
    return {
        "device_id": result.device_id,
        "command": result.command,
        "output": result.output,
        "timestamp": result.timestamp.isoformat(),
        "parsed": result.parsed,
        "error": result.error,
    }


def _from_row(row: _InvestigationRow) -> InvestigationReport:
    return InvestigationReport(
        incident_id=row.incident_id,
        status=row.status,
        started_at=row.started_at.replace(tzinfo=timezone.utc),
        completed_at=row.completed_at.replace(tzinfo=timezone.utc) if row.completed_at else None,
        summary=row.summary,
        error=row.error,
        command_results=[
            CommandResult(
                device_id=result["device_id"],
                command=result["command"],
                output=result["output"],
                timestamp=datetime.fromisoformat(result["timestamp"]),
                parsed=result.get("parsed"),
                error=result.get("error"),
            )
            for result in row.command_results or []
        ],
    )