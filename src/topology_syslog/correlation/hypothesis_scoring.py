"""Hypothesis scoring policy for hypothesis-based RCA."""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from topology_syslog.correlation.observation import Observation
from topology_syslog.topology.causal_topology import CausalTopology, device_object_id


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    value: float
    detail: str


@dataclass(frozen=True)
class Hypothesis:
    root_cause_object: str
    score: float
    covered_observations: tuple[int, ...]
    reasons: tuple[str, ...] = ()
    score_components: tuple[ScoreComponent, ...] = ()


class HypothesisScorer:
    def __init__(self, topology: CausalTopology) -> None:
        self._topology = topology

    def score(self, observations: tuple[Observation, ...]) -> tuple[Hypothesis, ...]:
        hypotheses = [
            hypothesis for candidate in self._candidate_objects(observations)
            if (hypothesis := self._score_candidate(candidate, observations)) is not None
        ]
        return tuple(sorted(
            hypotheses,
            key=lambda hypothesis: (
                hypothesis.score,
                _object_type_rank(self._topology.object_type(hypothesis.root_cause_object)),
                hypothesis.root_cause_object,
            ),
            reverse=True,
        ))

    def confidence(self, hypotheses: tuple[Hypothesis, ...]) -> float:
        if not hypotheses:
            return 0.0
        best = hypotheses[0]
        runner_up = hypotheses[1].score if len(hypotheses) > 1 else 0.0
        margin = best.score - runner_up
        coverage = _component_value(best, "coverage") / 100.0
        direct_evidence = min(1.0, _component_value(best, "direct_evidence") / 24.0)
        observation_count = max(1, len(best.covered_observations))
        sample_strength = min(1.0, observation_count / 3.0)
        confidence = (
            0.40 * min(1.0, max(0.0, (margin + 25.0) / 100.0))
            + 0.25 * coverage
            + 0.15 * direct_evidence
            + 0.20 * sample_strength
        )
        return round(min(1.0, max(0.0, confidence)), 3)

    def _score_candidate(self, candidate: str, observations: tuple[Observation, ...]) -> Hypothesis | None:
        covered: list[int] = []
        distances: list[int] = []
        direct_hits = 0
        direct_evidence = 0.0
        confidence_sum = 0.0
        for index, observation in enumerate(observations):
            distance = self._distance(candidate, observation.observed_object)
            if distance is None:
                continue
            covered.append(index)
            distances.append(distance)
            confidence_sum += observation.confidence
            if distance == 0:
                direct_hits += 1
                direct_evidence += 12.0 * observation.confidence
        if not covered:
            return None

        object_type = self._topology.object_type(candidate)
        average_distance = sum(distances) / len(distances)
        average_confidence = confidence_sum / len(covered)
        covered_observations = tuple(observations[index] for index in covered)
        temporal_fit = _temporal_fit(covered_observations, tuple(distances))
        components = (
            ScoreComponent(
                name="coverage",
                value=100.0 * (len(covered) / len(observations)),
                detail=f"explains {len(covered)} of {len(observations)} observation(s)",
            ),
            ScoreComponent(
                name="specificity",
                value=_specificity_score(object_type),
                detail=f"object type {object_type} specificity",
            ),
            ScoreComponent(
                name="direct_evidence",
                value=direct_evidence,
                detail=f"{direct_hits} confidence-weighted directly observed hit(s)",
            ),
            ScoreComponent(
                name="evidence_strength",
                value=10.0 * average_confidence,
                detail=f"average observation confidence {average_confidence:.3f}",
            ),
            ScoreComponent(
                name="silent_peer",
                value=self._silent_peer_score(candidate, covered_observations),
                detail="multiple observations naming the same peer strengthen silent device hypotheses",
            ),
            ScoreComponent(
                name="temporal_fit",
                value=temporal_fit,
                detail="closer causal observations should not arrive after downstream impact observations",
            ),
            ScoreComponent(
                name="contradiction",
                value=_contradiction_penalty(covered_observations),
                detail="recovery observations reduce fault hypothesis score",
            ),
            ScoreComponent(
                name="redundancy",
                value=self._redundancy_penalty(candidate, covered_observations),
                detail="partial redundant session impact reduces broad device hypotheses",
            ),
            ScoreComponent(
                name="link_coherence",
                value=18.0 if object_type == "physical-link" and len(covered) >= 2 else 0.0,
                detail="physical link explains multiple observations" if object_type == "physical-link" and len(covered) >= 2 else "not applicable",
            ),
            ScoreComponent(
                name="topology_distance",
                value=-4.0 * average_distance,
                detail=f"average topology distance {average_distance:.3f}",
            ),
        )
        score = round(sum(component.value for component in components), 3)
        return Hypothesis(
            root_cause_object=candidate,
            score=score,
            covered_observations=tuple(covered),
            reasons=tuple(_reason(candidate, observations[index]) for index in covered),
            score_components=tuple(
                ScoreComponent(component.name, round(component.value, 3), component.detail)
                for component in components
            ),
        )

    def _candidate_objects(self, observations: tuple[Observation, ...]) -> set[str]:
        candidates: set[str] = set()
        for observation in observations:
            observed_object = observation.observed_object
            if observed_object in self._topology.graph:
                candidates.add(observed_object)
                candidates.update(nx.ancestors(self._topology.graph, observed_object))
                candidates.update(self._topology.graph.predecessors(observed_object))
            candidates.add(device_object_id(observation.source_node))
        return candidates

    def _distance(self, candidate: str, observed_object: str) -> int | None:
        if candidate == observed_object:
            return 0
        if candidate not in self._topology.graph or observed_object not in self._topology.graph:
            return None
        try:
            return nx.shortest_path_length(self._topology.graph, candidate, observed_object)
        except nx.NetworkXNoPath:
            return None

    def _redundancy_penalty(self, candidate: str, observations: tuple[Observation, ...]) -> float:
        if self._topology.object_type(candidate) != "device":
            return 0.0
        all_sessions = {
            successor for successor in self._topology.graph.successors(candidate)
            if self._topology.object_type(successor) == "bgp-session"
        }
        covered_sessions = {
            observation.observed_object for observation in observations
            if self._topology.object_type(observation.observed_object) == "bgp-session"
        }
        if len(all_sessions) <= 1 or not covered_sessions:
            return 0.0
        uncovered = len(all_sessions - covered_sessions)
        if uncovered == 0:
            return 0.0
        return -8.0 * uncovered

    def _silent_peer_score(self, candidate: str, observations: tuple[Observation, ...]) -> float:
        if self._topology.object_type(candidate) != "device":
            return 0.0
        candidate_devices = self._topology.object_devices(candidate)
        if len(candidate_devices) != 1:
            return 0.0
        peer_hits = sum(1 for observation in observations if observation.peer_device == candidate_devices[0])
        if peer_hits < 2:
            strong_peer_hits = sum(
                1 for observation in observations
                if observation.peer_device == candidate_devices[0] and _strong_silent_peer_evidence(observation)
            )
            return 64.0 * strong_peer_hits
        return 14.0 * peer_hits


def _specificity_score(object_type: str) -> float:
    return {
        "physical-link": 28.0,
        "interface": 24.0,
        "bgp-session": 24.0,
        "device": 8.0,
    }.get(object_type, 0.0)


def _object_type_rank(object_type: str) -> int:
    return {
        "physical-link": 4,
        "interface": 3,
        "bgp-session": 3,
        "device": 2,
    }.get(object_type, 0)


def _component_value(hypothesis: Hypothesis, name: str) -> float:
    return next((component.value for component in hypothesis.score_components if component.name == name), 0.0)


def _contradiction_penalty(observations: tuple[Observation, ...]) -> float:
    return -35.0 * sum(1 for observation in observations if observation.assertion == "recovery")


def _temporal_fit(observations: tuple[Observation, ...], distances: tuple[int, ...]) -> float:
    if len(observations) < 2:
        return 0.0
    ordered = sorted(zip(observations, distances), key=lambda item: item[0].observed_at)
    score = 0.0
    for left_index, (_, left_distance) in enumerate(ordered):
        for _, right_distance in ordered[left_index + 1:]:
            if left_distance < right_distance:
                score += 4.0
            elif left_distance > right_distance:
                score -= 4.0
    return max(-12.0, min(12.0, score))


def _reason(candidate: str, observation: Observation) -> str:
    if candidate == observation.observed_object:
        return f"{candidate} was directly observed as faulty"
    return f"{candidate} can explain {observation.observed_object} through topology dependency"


def _strong_silent_peer_evidence(observation: Observation) -> bool:
    message = observation.raw_message.lower()
    return "removed from session" in message or "hold time expired" in message