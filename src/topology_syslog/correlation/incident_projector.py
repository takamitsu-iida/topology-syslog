"""Project hypothesis RCA results into the legacy Incident model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from topology_syslog.correlation.hypothesis_rca import RCAResult
from topology_syslog.correlation.observation import Observation
from topology_syslog.models import Incident, RCAEvidence, RCAExplanation, RCACandidate
from topology_syslog.topology.causal_topology import CausalTopology


class ProjectionEventType(StrEnum):
    INCIDENT_CANDIDATE = "INCIDENT_CANDIDATE"
    RCA_REVISED = "RCA_REVISED"


@dataclass(frozen=True)
class ProjectionEvent:
    event_type: ProjectionEventType
    incident: Incident
    root_cause_object: str
    previous_root_cause_object: str | None = None


class IncidentProjector:
    def __init__(self, topology: CausalTopology) -> None:
        self._topology = topology
        self._counters: dict[str, int] = {}

    def project(
        self,
        result: RCAResult,
        *,
        previous_root_cause_object: str | None = None,
        projected_at: datetime | None = None,
    ) -> ProjectionEvent | None:
        if result.root_cause_object is None:
            return None
        created_at = projected_at or _first_observed_at(result.observations) or datetime.now(tz=timezone.utc)
        incident = Incident(
            incident_id=self._new_id(created_at),
            created_at=created_at,
            root_cause_node=self._root_cause_node(result.root_cause_object),
            primary_event=_primary_event(result),
            secondary_nodes=self._secondary_nodes(result),
            raw_log_count=len(result.observations),
            raw_logs=[observation.raw_message for observation in result.observations],
            status="OPEN",
            last_fault_at=_last_fault_at(result.observations),
            rca_explanation=self._explanation(result),
        )
        return ProjectionEvent(
            event_type=ProjectionEventType.RCA_REVISED if previous_root_cause_object else ProjectionEventType.INCIDENT_CANDIDATE,
            incident=incident,
            root_cause_object=result.root_cause_object,
            previous_root_cause_object=previous_root_cause_object,
        )

    def _root_cause_node(self, root_cause_object: str) -> str:
        devices = self._topology.object_devices(root_cause_object)
        if devices:
            return devices[0]
        if root_cause_object.startswith("Device:"):
            return root_cause_object.split(":", 1)[1]
        return root_cause_object

    def _secondary_nodes(self, result: RCAResult) -> list[str]:
        root_node = self._root_cause_node(result.root_cause_object or "")
        secondary = [
            observation.source_node for observation in result.observations
            if observation.source_node != root_node
        ]
        return list(dict.fromkeys(secondary))

    def _explanation(self, result: RCAResult) -> RCAExplanation:
        best = result.hypotheses[0] if result.hypotheses else None
        if best is None or result.root_cause_object is None:
            return RCAExplanation(confidence=result.confidence)
        root_node = self._root_cause_node(result.root_cause_object)
        evidences = [
            RCAEvidence(
                source="hypothesis-score",
                summary=f"{component.name}: {component.detail}",
                weight=component.value,
                related_nodes=[root_node],
                related_log_ids=[result.root_cause_object],
            )
            for component in best.score_components
        ]
        primary = RCACandidate(
            node_id=root_node,
            confidence=result.confidence,
            evidences=evidences,
            secondary_nodes=self._secondary_nodes(result),
        )
        alternatives = [
            RCACandidate(
                node_id=self._root_cause_node(hypothesis.root_cause_object),
                confidence=0.0,
                alternative_reason=f"candidate object {hypothesis.root_cause_object} scored {hypothesis.score}",
            )
            for hypothesis in result.hypotheses[1:4]
        ]
        return RCAExplanation(
            confidence=result.confidence,
            primary_candidate=primary,
            alternative_candidates=alternatives,
        )

    def _new_id(self, created_at: datetime) -> str:
        date_str = created_at.strftime("%Y%m%d")
        self._counters[date_str] = self._counters.get(date_str, 0) + 1
        return f"INC-{date_str}-{self._counters[date_str]:03d}"


def _primary_event(result: RCAResult) -> str:
    if not result.observations:
        return result.root_cause_object or "unknown"
    return result.observations[0].raw_message


def _first_observed_at(observations: tuple[Observation, ...]) -> datetime | None:
    return min((observation.observed_at for observation in observations), default=None)


def _last_fault_at(observations: tuple[Observation, ...]) -> datetime | None:
    faults = [observation.observed_at for observation in observations if observation.assertion == "fault"]
    return max(faults, default=None)