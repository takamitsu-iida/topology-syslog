"""Migration readiness evaluation for legacy vs hypothesis RCA."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RCASampleEvaluation:
    sample_id: str
    expected_root_cause_object: str
    expected_legacy_nodes: tuple[str, ...]
    legacy_roots: tuple[str, ...]
    hypothesis_root: str | None
    hypothesis_confidence: float
    legacy_matches_expected: bool
    hypothesis_matches_expected: bool
    root_object_type: str


@dataclass(frozen=True)
class RCAMigrationReadiness:
    ready: bool
    recommended_engine: str
    rollback_engine: str
    total_samples: int
    legacy_accuracy: float
    hypothesis_accuracy: float
    average_hypothesis_confidence: float
    min_required_accuracy: float
    min_required_confidence: float
    object_type_accuracy: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    samples: tuple[RCASampleEvaluation, ...] = ()


def evaluate_migration_readiness(
    samples: list[RCASampleEvaluation],
    *,
    min_accuracy: float = 0.8,
    min_confidence: float = 0.6,
) -> RCAMigrationReadiness:
    if not 0.0 <= min_accuracy <= 1.0:
        raise ValueError("min_accuracy must be between 0.0 and 1.0")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")
    total = len(samples)
    if total == 0:
        return RCAMigrationReadiness(
            ready=False,
            recommended_engine="dual",
            rollback_engine="legacy",
            total_samples=0,
            legacy_accuracy=0.0,
            hypothesis_accuracy=0.0,
            average_hypothesis_confidence=0.0,
            min_required_accuracy=min_accuracy,
            min_required_confidence=min_confidence,
            reasons=("no labeled samples were provided",),
        )

    legacy_accuracy = _ratio(sum(1 for sample in samples if sample.legacy_matches_expected), total)
    hypothesis_accuracy = _ratio(sum(1 for sample in samples if sample.hypothesis_matches_expected), total)
    average_confidence = round(sum(sample.hypothesis_confidence for sample in samples) / total, 3)
    object_type_accuracy = _object_type_accuracy(samples)

    reasons: list[str] = []
    if hypothesis_accuracy < min_accuracy:
        reasons.append(f"hypothesis accuracy {hypothesis_accuracy:.3f} is below required {min_accuracy:.3f}")
    if average_confidence < min_confidence:
        reasons.append(f"average hypothesis confidence {average_confidence:.3f} is below required {min_confidence:.3f}")
    if hypothesis_accuracy < legacy_accuracy:
        reasons.append(f"hypothesis accuracy {hypothesis_accuracy:.3f} is below legacy accuracy {legacy_accuracy:.3f}")
    if any(sample.hypothesis_root is None for sample in samples):
        reasons.append("one or more samples did not produce a hypothesis root")

    ready = not reasons
    if ready:
        reasons.append("hypothesis RCA met the migration criteria")
    return RCAMigrationReadiness(
        ready=ready,
        recommended_engine="hypothesis" if ready else "dual",
        rollback_engine="legacy",
        total_samples=total,
        legacy_accuracy=legacy_accuracy,
        hypothesis_accuracy=hypothesis_accuracy,
        average_hypothesis_confidence=average_confidence,
        min_required_accuracy=min_accuracy,
        min_required_confidence=min_confidence,
        object_type_accuracy=object_type_accuracy,
        reasons=tuple(reasons),
        samples=tuple(samples),
    )


def readiness_to_dict(readiness: RCAMigrationReadiness) -> dict:
    return {
        "ready": readiness.ready,
        "recommended_engine": readiness.recommended_engine,
        "rollback_engine": readiness.rollback_engine,
        "total_samples": readiness.total_samples,
        "legacy_accuracy": readiness.legacy_accuracy,
        "hypothesis_accuracy": readiness.hypothesis_accuracy,
        "average_hypothesis_confidence": readiness.average_hypothesis_confidence,
        "min_required_accuracy": readiness.min_required_accuracy,
        "min_required_confidence": readiness.min_required_confidence,
        "object_type_accuracy": readiness.object_type_accuracy,
        "reasons": list(readiness.reasons),
        "samples": [
            {
                "sample_id": sample.sample_id,
                "expected_root_cause_object": sample.expected_root_cause_object,
                "expected_legacy_nodes": list(sample.expected_legacy_nodes),
                "legacy_roots": list(sample.legacy_roots),
                "hypothesis_root": sample.hypothesis_root,
                "hypothesis_confidence": sample.hypothesis_confidence,
                "legacy_matches_expected": sample.legacy_matches_expected,
                "hypothesis_matches_expected": sample.hypothesis_matches_expected,
                "root_object_type": sample.root_object_type,
            }
            for sample in readiness.samples
        ],
    }


def _object_type_accuracy(samples: list[RCASampleEvaluation]) -> dict[str, float]:
    counts: dict[str, int] = {}
    matches: dict[str, int] = {}
    for sample in samples:
        counts[sample.root_object_type] = counts.get(sample.root_object_type, 0) + 1
        if sample.hypothesis_matches_expected:
            matches[sample.root_object_type] = matches.get(sample.root_object_type, 0) + 1
    return {object_type: _ratio(matches.get(object_type, 0), total) for object_type, total in counts.items()}


def _ratio(value: int, total: int) -> float:
    return round(value / total, 3) if total else 0.0