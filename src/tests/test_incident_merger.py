from datetime import datetime, timedelta, timezone

import networkx as nx

from topology_syslog.correlation.incident_merger import IncidentMerger, MergeAction
from topology_syslog.models import Incident
from topology_syslog.topology.graph_engine import GraphEngine

_IDS: dict[str, int] = {}


def _engine() -> GraphEngine:
    graph = nx.DiGraph()
    graph.add_edge("Spine1", "Leaf1")
    graph.add_edge("Spine1", "Leaf2")
    graph.add_edge("Leaf2", "Host1")
    graph.add_edge("Branch1", "BranchLeaf1")
    return GraphEngine(graph)


def _incident(root: str, *, secondary: list[str] | None = None, raw: list[str] | None = None) -> Incident:
    raw_logs = raw or [f"{root} event"]
    _IDS.setdefault(root, len(_IDS) + 1)
    return Incident(
        incident_id=f"INC-20260902-{_IDS[root]:03d}",
        created_at=datetime.now(tz=timezone.utc),
        root_cause_node=root,
        primary_event=raw_logs[0],
        secondary_nodes=secondary or [],
        raw_log_count=len(raw_logs),
        raw_logs=raw_logs,
    )


def test_same_root_appends_to_existing_incident():
    merger = IncidentMerger()
    graph = _engine()
    target = _incident("Spine1", secondary=["Leaf1"], raw=["spine down"])
    candidate = _incident("Spine1", secondary=["Leaf2"], raw=["spine still down"])

    decision = merger.find_merge_target(candidate, [target], graph)
    merged = merger.merge(decision.target, candidate, graph)

    assert decision.action == MergeAction.APPEND
    assert merged.root_cause_node == "Spine1"
    assert merged.secondary_nodes == ["Leaf1", "Leaf2"]
    assert merged.raw_log_count == 2
    assert merged.raw_logs == ["spine down", "spine still down"]


def test_descendant_candidate_appends_as_secondary():
    merger = IncidentMerger()
    graph = _engine()
    target = _incident("Spine1", raw=["spine down"])
    candidate = _incident("Leaf1", raw=["leaf bgp down"])

    decision = merger.find_merge_target(candidate, [target], graph)
    merged = merger.merge(decision.target, candidate, graph)

    assert decision.action == MergeAction.APPEND
    assert merged.root_cause_node == "Spine1"
    assert merged.secondary_nodes == ["Leaf1"]
    assert merged.raw_log_count == 2


def test_ancestor_candidate_promotes_root_cause():
    merger = IncidentMerger()
    graph = _engine()
    target = _incident("Leaf2", secondary=["Host1"], raw=["leaf bgp down"])
    candidate = _incident("Spine1", raw=["spine interface down"])

    decision = merger.find_merge_target(candidate, [target], graph)
    merged = merger.merge(decision.target, candidate, graph)

    assert decision.action == MergeAction.PROMOTE_ROOT
    assert merged.root_cause_node == "Spine1"
    assert merged.primary_event == "spine interface down"
    assert merged.secondary_nodes == ["Leaf2", "Host1"]
    assert merged.raw_log_count == 2


def test_unrelated_candidate_stays_new():
    decision = IncidentMerger().find_merge_target(
        _incident("Branch1"),
        [_incident("Spine1")],
        _engine(),
    )

    assert decision.action == MergeAction.NEW
    assert decision.target is None


def test_related_candidate_after_merge_window_stays_new():
    merger = IncidentMerger(merge_window_sec=120)
    graph = _engine()
    target = _incident("Spine1", raw=["first link down"])
    target.last_fault_at = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
    candidate = _incident("Leaf1", raw=["later independent link down"])
    candidate.last_fault_at = target.last_fault_at + timedelta(seconds=121)

    decision = merger.find_merge_target(candidate, [target], graph)

    assert decision.action == MergeAction.NEW
    assert decision.target is None


def test_related_candidate_within_merge_window_still_appends():
    merger = IncidentMerger(merge_window_sec=120)
    graph = _engine()
    target = _incident("Spine1", raw=["spine down"])
    target.last_fault_at = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
    candidate = _incident("Leaf1", raw=["leaf bgp down"])
    candidate.last_fault_at = target.last_fault_at + timedelta(seconds=120)

    decision = merger.find_merge_target(candidate, [target], graph)

    assert decision.action == MergeAction.APPEND
    assert decision.target is target