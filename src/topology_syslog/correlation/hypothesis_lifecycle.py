"""Lifecycle handling for projected hypothesis RCA incidents."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from topology_syslog.correlation.observation import Observation
from topology_syslog.models import Incident, IncidentCondition
from topology_syslog.topology.causal_topology import CausalTopology


class HypothesisLifecycleEventType(StrEnum):
    NO_MATCH = "NO_MATCH"
    RECOVERING = "RECOVERING"
    DEGRADED = "DEGRADED"
    RECOVERED = "RECOVERED"
    FLAPPING = "FLAPPING"
    FAULT_APPLIED = "FAULT_APPLIED"


@dataclass(frozen=True)
class HypothesisLifecycleEvent:
    event_type: HypothesisLifecycleEventType
    incident: Incident | None = None
    matched_root_cause_object: str | None = None
    evidence: str | None = None


class HypothesisIncidentLifecycle:
    def __init__(
        self,
        topology: CausalTopology,
        *,
        quiet_period_sec: float = 30.0,
        flap_threshold: int = 2,
    ) -> None:
        if quiet_period_sec < 0:
            raise ValueError("quiet_period_sec must be non-negative")
        if flap_threshold < 1:
            raise ValueError("flap_threshold must be positive")
        self._topology = topology
        self._quiet_period = timedelta(seconds=quiet_period_sec)
        self._flap_threshold = flap_threshold

    def apply_recovery(self, incident: Incident, observation: Observation) -> HypothesisLifecycleEvent:
        if incident.status != "OPEN" or observation.assertion != "recovery":
            return HypothesisLifecycleEvent(HypothesisLifecycleEventType.NO_MATCH)
        root_object = _root_cause_object(incident)
        if root_object is None or not self._is_related_recovery(root_object, observation.observed_object):
            return HypothesisLifecycleEvent(HypothesisLifecycleEventType.NO_MATCH)

        incident.last_recovery_at = observation.observed_at
        if observation.raw_message not in incident.recovery_evidence:
            incident.recovery_evidence.append(observation.raw_message)

        if observation.observed_object == root_object or self._topology.object_type(root_object) in {"physical-link", "device"}:
            incident.condition = IncidentCondition.RECOVERING.value
            event_type = HypothesisLifecycleEventType.RECOVERING
        else:
            incident.condition = IncidentCondition.DEGRADED.value
            event_type = HypothesisLifecycleEventType.DEGRADED
        return HypothesisLifecycleEvent(
            event_type=event_type,
            incident=incident,
            matched_root_cause_object=root_object,
            evidence=observation.raw_message,
        )

    def apply_fault(self, incident: Incident, observation: Observation) -> HypothesisLifecycleEvent:
        if incident.status != "OPEN" or observation.assertion != "fault":
            return HypothesisLifecycleEvent(HypothesisLifecycleEventType.NO_MATCH)
        root_object = _root_cause_object(incident)
        if root_object is not None and not self._is_related_recovery(root_object, observation.observed_object):
            return HypothesisLifecycleEvent(HypothesisLifecycleEventType.NO_MATCH)

        incident.last_fault_at = observation.observed_at
        if incident.condition in {IncidentCondition.RECOVERING.value, IncidentCondition.RECOVERED.value}:
            incident.flap_count += 1
            if incident.flap_count >= self._flap_threshold:
                incident.condition = IncidentCondition.FLAPPING.value
                event_type = HypothesisLifecycleEventType.FLAPPING
            else:
                incident.condition = IncidentCondition.ACTIVE.value
                event_type = HypothesisLifecycleEventType.FAULT_APPLIED
        elif incident.condition == IncidentCondition.FLAPPING.value:
            incident.flap_count += 1
            event_type = HypothesisLifecycleEventType.FLAPPING
        else:
            incident.condition = IncidentCondition.ACTIVE.value
            event_type = HypothesisLifecycleEventType.FAULT_APPLIED
        return HypothesisLifecycleEvent(
            event_type=event_type,
            incident=incident,
            matched_root_cause_object=root_object,
            evidence=observation.raw_message,
        )

    def confirm_recovered(self, incident: Incident, at: datetime) -> HypothesisLifecycleEvent:
        if incident.status != "OPEN" or incident.condition != IncidentCondition.RECOVERING.value:
            return HypothesisLifecycleEvent(HypothesisLifecycleEventType.NO_MATCH)
        if incident.last_recovery_at is None or at - incident.last_recovery_at < self._quiet_period:
            return HypothesisLifecycleEvent(HypothesisLifecycleEventType.NO_MATCH)
        if incident.last_fault_at is not None and incident.last_fault_at > incident.last_recovery_at:
            return HypothesisLifecycleEvent(HypothesisLifecycleEventType.NO_MATCH)
        incident.condition = IncidentCondition.RECOVERED.value
        return HypothesisLifecycleEvent(
            event_type=HypothesisLifecycleEventType.RECOVERED,
            incident=incident,
            matched_root_cause_object=_root_cause_object(incident),
        )

    def _is_related_recovery(self, root_object: str, observed_object: str) -> bool:
        if observed_object == root_object:
            return True
        if root_object not in self._topology.graph or observed_object not in self._topology.graph:
            return False
        if self._topology.graph.has_edge(root_object, observed_object):
            return True
        if self._topology.graph.has_edge(observed_object, root_object):
            return True
        return observed_object in self._topology.graph.successors(root_object)


def _root_cause_object(incident: Incident) -> str | None:
    explanation = incident.rca_explanation
    if explanation.primary_candidate is None:
        return None
    for evidence in explanation.primary_candidate.evidences:
        for related_log_id in evidence.related_log_ids:
            if ":" in related_log_id:
                return related_log_id
    return None