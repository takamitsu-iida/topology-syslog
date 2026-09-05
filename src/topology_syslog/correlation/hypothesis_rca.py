"""Experimental hypothesis-based RCA engine.

This module is intentionally isolated from the current ingestion and incident
pipeline. It treats syslog lines as observations, scores topology-backed root
cause hypotheses, and returns an RCA result without creating incidents.
"""
from __future__ import annotations

from dataclasses import dataclass

from topology_syslog.correlation.hypothesis_scoring import Hypothesis, HypothesisScorer
from topology_syslog.correlation.observation import Observation, ObservationNormalizer
from topology_syslog.models import SyslogMessage
from topology_syslog.topology.causal_topology import CausalTopology


@dataclass(frozen=True)
class RCAResult:
    root_cause_object: str | None
    confidence: float
    hypotheses: tuple[Hypothesis, ...] = ()
    observations: tuple[Observation, ...] = ()


class HypothesisRCAEngine:
    def __init__(self, topology: CausalTopology) -> None:
        self._normalizer = ObservationNormalizer(topology)
        self._scorer = HypothesisScorer(topology)

    def observe(self, message: SyslogMessage) -> Observation | None:
        return self._normalizer.normalize(message)

    def infer(self, messages: list[SyslogMessage]) -> RCAResult:
        observations = tuple(
            observation for message in messages
            if (observation := self.observe(message)) is not None
        )
        if not observations:
            return RCAResult(root_cause_object=None, confidence=0.0)

        hypotheses = self._scorer.score(observations)
        if not hypotheses:
            return RCAResult(root_cause_object=None, confidence=0.0, observations=observations)

        return RCAResult(
            root_cause_object=hypotheses[0].root_cause_object,
            confidence=self._scorer.confidence(hypotheses),
            hypotheses=hypotheses,
            observations=observations,
        )
