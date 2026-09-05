"""Event-time Observation buffer for hypothesis-based RCA."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from topology_syslog.correlation.hypothesis_rca import RCAResult
from topology_syslog.correlation.hypothesis_scoring import HypothesisScorer
from topology_syslog.correlation.observation import Observation
from topology_syslog.topology.causal_topology import CausalTopology


class BufferUpdateType(StrEnum):
    BUFFERED = "BUFFERED"
    TENTATIVE = "TENTATIVE"
    RCA_REVISED = "RCA_REVISED"
    WINDOW_CLOSED = "WINDOW_CLOSED"


@dataclass(frozen=True)
class BufferUpdate:
    update_type: BufferUpdateType
    result: RCAResult | None = None
    previous_root_cause_object: str | None = None
    current_root_cause_object: str | None = None


class ObservationBuffer:
    def __init__(
        self,
        topology: CausalTopology,
        *,
        window_sec: float = 10.0,
        early_confidence: float = 0.5,
    ) -> None:
        if window_sec <= 0:
            raise ValueError("window_sec must be positive")
        self._window = timedelta(seconds=window_sec)
        self._early_confidence = early_confidence
        self._scorer = HypothesisScorer(topology)
        self._observations: list[Observation] = []
        self._last_result: RCAResult | None = None

    @property
    def observations(self) -> tuple[Observation, ...]:
        return tuple(self._observations)

    def add(self, observation: Observation, *, received_at: datetime | None = None) -> BufferUpdate:
        if received_at is not None:
            observation = _with_received_at(observation, received_at)
        if self._observations and not self._fits_active_window(observation):
            closed = self.close_window()
            self._observations = [observation]
            self._last_result = None
            current = self._evaluate()
            return current if current.result is not None else closed

        self._observations.append(observation)
        return self._evaluate()

    def close_window(self) -> BufferUpdate:
        if not self._observations:
            return BufferUpdate(BufferUpdateType.BUFFERED)
        result = self._build_result()
        self._observations = []
        self._last_result = None
        return BufferUpdate(
            update_type=BufferUpdateType.WINDOW_CLOSED,
            result=result,
            current_root_cause_object=result.root_cause_object,
        )

    def _evaluate(self) -> BufferUpdate:
        result = self._build_result()
        if result.root_cause_object is None:
            return BufferUpdate(BufferUpdateType.BUFFERED, result=result)

        previous = self._last_result.root_cause_object if self._last_result is not None else None
        self._last_result = result
        if previous is not None and previous != result.root_cause_object:
            return BufferUpdate(
                update_type=BufferUpdateType.RCA_REVISED,
                result=result,
                previous_root_cause_object=previous,
                current_root_cause_object=result.root_cause_object,
            )
        if result.confidence >= self._early_confidence:
            return BufferUpdate(
                update_type=BufferUpdateType.TENTATIVE,
                result=result,
                current_root_cause_object=result.root_cause_object,
            )
        return BufferUpdate(
            update_type=BufferUpdateType.BUFFERED,
            result=result,
            current_root_cause_object=result.root_cause_object,
        )

    def _build_result(self) -> RCAResult:
        observations = tuple(sorted(self._observations, key=lambda observation: observation.observed_at))
        hypotheses = self._scorer.score(observations)
        if not hypotheses:
            return RCAResult(root_cause_object=None, confidence=0.0, observations=observations)
        return RCAResult(
            root_cause_object=hypotheses[0].root_cause_object,
            confidence=self._scorer.confidence(hypotheses),
            hypotheses=hypotheses,
            observations=observations,
        )

    def _fits_active_window(self, observation: Observation) -> bool:
        event_times = [current.observed_at for current in self._observations]
        start = min([*event_times, observation.observed_at])
        end = max([*event_times, observation.observed_at])
        return end - start <= self._window


def _with_received_at(observation: Observation, received_at: datetime) -> Observation:
    return Observation(
        observed_at=observation.observed_at,
        source_node=observation.source_node,
        observed_object=observation.observed_object,
        assertion=observation.assertion,
        signature=observation.signature,
        severity=observation.severity,
        raw_message=observation.raw_message,
        confidence=observation.confidence,
        received_at=received_at,
        classification=observation.classification,
        action=observation.action,
        knowledge_id=observation.knowledge_id,
        peer_device=observation.peer_device,
    )