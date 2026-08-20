from datetime import datetime, timezone

import pytest

from topology_syslog.models import Incident
from topology_syslog.persistence.incident_store import IncidentStore


def _store() -> IncidentStore:
    return IncidentStore("sqlite:///:memory:")


def _inc(
    incident_id: str = "INC-20260816-001",
    status: str = "OPEN",
    created_at: datetime | None = None,
) -> Incident:
    return Incident(
        incident_id=incident_id,
        created_at=created_at or datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="%LINK-3-UPDOWN: Interface GE0/0 down",
        secondary_nodes=["Dist-Switch1", "Access-SW1"],
        raw_log_count=3,
        status=status,
    )


def test_save_and_get_by_id():
    store = _store()
    inc = _inc()
    store.save(inc)
    result = store.get_by_id(inc.incident_id)
    assert result is not None
    assert result.incident_id == inc.incident_id
    assert result.root_cause_node == "Core-Router1"
    assert result.secondary_nodes == ["Dist-Switch1", "Access-SW1"]
    assert result.status == "OPEN"


def test_get_by_id_not_found():
    store = _store()
    assert store.get_by_id("INC-99991231-999") is None


def test_list_all():
    store = _store()
    store.save(_inc("INC-20260816-001"))
    store.save(_inc("INC-20260816-002"))
    results = store.list_incidents()
    assert len(results) == 2


def test_list_filter_by_status():
    store = _store()
    store.save(_inc("INC-20260816-001", status="OPEN"))
    store.save(_inc("INC-20260816-002", status="CLOSED"))
    open_only = store.list_incidents(status="OPEN")
    assert len(open_only) == 1
    assert open_only[0].status == "OPEN"


def test_list_filter_by_date_range():
    store = _store()
    store.save(_inc("INC-A", created_at=datetime(2026, 8, 16, 8, 0, 0, tzinfo=timezone.utc)))
    store.save(_inc("INC-B", created_at=datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc)))
    store.save(_inc("INC-C", created_at=datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)))

    from_dt = datetime(2026, 8, 16, 9, 0, 0, tzinfo=timezone.utc)
    to_dt   = datetime(2026, 8, 16, 11, 0, 0, tzinfo=timezone.utc)
    results = store.list_incidents(from_dt=from_dt, to_dt=to_dt)
    assert len(results) == 1
    assert results[0].incident_id == "INC-B"


def test_list_ordered_by_desc_created_at():
    store = _store()
    store.save(_inc("INC-OLDER", created_at=datetime(2026, 8, 16, 9, 0, 0, tzinfo=timezone.utc)))
    store.save(_inc("INC-NEWER", created_at=datetime(2026, 8, 16, 11, 0, 0, tzinfo=timezone.utc)))
    results = store.list_incidents()
    assert results[0].incident_id == "INC-NEWER"


def test_resolve_existing():
    store = _store()
    inc = _inc()
    store.save(inc)
    ok = store.resolve(inc.incident_id)
    assert ok is True
    updated = store.get_by_id(inc.incident_id)
    assert updated.status == "CLOSED"


def test_resolve_nonexistent():
    store = _store()
    ok = store.resolve("INC-99991231-999")
    assert ok is False


def test_save_overwrites_on_same_id():
    store = _store()
    inc = _inc()
    store.save(inc)
    inc_updated = Incident(
        incident_id=inc.incident_id,
        created_at=inc.created_at,
        root_cause_node=inc.root_cause_node,
        primary_event="updated event",
        secondary_nodes=[],
        raw_log_count=1,
        status="CLOSED",
    )
    store.save(inc_updated)
    result = store.get_by_id(inc.incident_id)
    assert result.primary_event == "updated event"
    assert result.status == "CLOSED"


def test_created_at_tz_preserved():
    store = _store()
    inc = _inc()
    store.save(inc)
    result = store.get_by_id(inc.incident_id)
    assert result.created_at.tzinfo is not None
    assert result.created_at == inc.created_at
