"""既存インシデントへの統合ポリシー。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from topology_syslog.models import Incident
from topology_syslog.topology.graph_engine import GraphEngine


class MergeAction(StrEnum):
    NEW = "NEW"
    APPEND = "APPEND"
    PROMOTE_ROOT = "PROMOTE_ROOT"


@dataclass(frozen=True)
class MergeDecision:
    action: MergeAction
    target: Incident | None = None


class IncidentMerger:
    def find_merge_target(
        self,
        candidate: Incident,
        open_incidents: list[Incident],
        graph: GraphEngine,
    ) -> MergeDecision:
        for existing in open_incidents:
            if existing.root_cause_node == candidate.root_cause_node:
                return MergeDecision(MergeAction.APPEND, existing)

        for existing in open_incidents:
            if self._is_descendant(candidate.root_cause_node, existing.root_cause_node, graph):
                return MergeDecision(MergeAction.APPEND, existing)

        for existing in open_incidents:
            if self._is_ancestor(candidate.root_cause_node, existing.root_cause_node, graph):
                if candidate.root_cause_node in existing.secondary_nodes:
                    return MergeDecision(MergeAction.APPEND, existing)
                return MergeDecision(MergeAction.PROMOTE_ROOT, existing)

        return MergeDecision(MergeAction.NEW)

    def merge(
        self,
        target: Incident,
        candidate: Incident,
        graph: GraphEngine,
    ) -> Incident:
        if (
            self._is_ancestor(candidate.root_cause_node, target.root_cause_node, graph)
            and candidate.root_cause_node not in target.secondary_nodes
        ):
            old_root = target.root_cause_node
            target.root_cause_node = candidate.root_cause_node
            target.primary_event = candidate.primary_event
            target.secondary_nodes = self._dedupe_secondary(target.root_cause_node, [
                old_root,
                *target.secondary_nodes,
                *candidate.secondary_nodes,
            ])
        else:
            target.secondary_nodes = self._dedupe_secondary(target.root_cause_node, [
                *target.secondary_nodes,
                candidate.root_cause_node,
                *candidate.secondary_nodes,
            ])

        target.raw_logs = [*target.raw_logs, *candidate.raw_logs]
        target.raw_log_count += candidate.raw_log_count
        if candidate.condition == "FLAPPING" or target.condition == "FLAPPING":
            target.condition = "FLAPPING"
        target.maintenance_plan_id = target.maintenance_plan_id or candidate.maintenance_plan_id
        return target

    def _is_ancestor(self, maybe_ancestor: str, node: str, graph: GraphEngine) -> bool:
        return maybe_ancestor in graph.get_ancestors(node)

    def _is_descendant(self, maybe_descendant: str, node: str, graph: GraphEngine) -> bool:
        return maybe_descendant in graph.get_descendants(node)

    def _dedupe_secondary(self, root_cause_node: str, nodes: list[str]) -> list[str]:
        return [node for node in dict.fromkeys(nodes) if node != root_cause_node]