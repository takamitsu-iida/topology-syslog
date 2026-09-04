from __future__ import annotations

from datetime import datetime, timedelta, timezone

from topology_syslog.node_monitor.models import NodeState, NodeStateRecord, ProbeResult
from topology_syslog.node_monitor.store import InMemoryNodeStateStore


_OBSERVED_AT = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)


def _record(node_id: str = "Spine2") -> NodeStateRecord:
    return NodeStateRecord(
        node_id=node_id,
        state=NodeState.UP,
        observed_at=_OBSERVED_AT,
        expires_at=_OBSERVED_AT + timedelta(seconds=60),
        reason="TCP connection succeeded.",
        probes=(ProbeResult(
            probe_type="tcp",
            target="10.0.0.2:179",
            success=True,
            observed_at=_OBSERVED_AT,
        ),),
        monitor_id="monitor-1",
    )


def test_store_returns_unexpired_state_record():
    store = InMemoryNodeStateStore()
    record = _record()
    store.put(record)

    actual = store.get("Spine2", now=_OBSERVED_AT + timedelta(seconds=59))

    assert actual == record


def test_store_returns_unknown_for_unobserved_node():
    actual = InMemoryNodeStateStore().get("Spine2", now=_OBSERVED_AT)

    assert actual.node_id == "Spine2"
    assert actual.state == NodeState.UNKNOWN
    assert actual.reason == "No state has been observed."


def test_store_returns_unknown_when_state_has_expired_without_overwriting_record():
    store = InMemoryNodeStateStore()
    record = _record()
    store.put(record)

    expired = store.get("Spine2", now=record.expires_at)
    unexpired = store.get("Spine2", now=_OBSERVED_AT + timedelta(seconds=59))

    assert expired.state == NodeState.UNKNOWN
    assert expired.reason == "The last observed state has expired."
    assert unexpired == record


def test_store_returns_states_for_multiple_nodes_in_requested_order():
    store = InMemoryNodeStateStore()
    store.put(_record("Spine1"))
    store.put(_record("Spine2"))

    states = store.get_many(["Spine2", "Leaf1", "Spine1"], now=_OBSERVED_AT)

    assert [state.node_id for state in states] == ["Spine2", "Leaf1", "Spine1"]
    assert [state.state for state in states] == [NodeState.UP, NodeState.UNKNOWN, NodeState.UP]