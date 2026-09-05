from topology_syslog.correlation.rca_migration import RCASampleEvaluation, evaluate_migration_readiness, readiness_to_dict


def _sample(sample_id: str, expected: str, actual: str | None, *, confidence: float = 0.8) -> RCASampleEvaluation:
    return RCASampleEvaluation(
        sample_id=sample_id,
        expected_root_cause_object=expected,
        expected_legacy_nodes=("Spine1",),
        legacy_roots=("Spine1",),
        hypothesis_root=actual,
        hypothesis_confidence=confidence,
        legacy_matches_expected=True,
        hypothesis_matches_expected=expected == actual,
        root_object_type=expected.split(":", 1)[0],
    )


def test_migration_readiness_recommends_hypothesis_when_criteria_are_met():
    readiness = evaluate_migration_readiness([
        _sample("link", "PhysicalLink:Leaf1:Gi0/0--Spine1:Gi0/0", "PhysicalLink:Leaf1:Gi0/0--Spine1:Gi0/0"),
        _sample("device", "Device:Spine1", "Device:Spine1"),
        _sample("session", "BGPSession:Spine1-Leaf1-eBGP", "BGPSession:Spine1-Leaf1-eBGP"),
    ], min_accuracy=0.8, min_confidence=0.6)

    assert readiness.ready is True
    assert readiness.recommended_engine == "hypothesis"
    assert readiness.rollback_engine == "legacy"
    assert readiness.hypothesis_accuracy == 1.0
    assert readiness.object_type_accuracy == {"PhysicalLink": 1.0, "Device": 1.0, "BGPSession": 1.0}


def test_migration_readiness_keeps_dual_when_hypothesis_is_below_threshold():
    readiness = evaluate_migration_readiness([
        _sample("link", "PhysicalLink:Leaf1:Gi0/0--Spine1:Gi0/0", "Device:Spine1"),
        _sample("device", "Device:Spine1", "Device:Spine1"),
    ], min_accuracy=0.8, min_confidence=0.6)

    assert readiness.ready is False
    assert readiness.recommended_engine == "dual"
    assert readiness.rollback_engine == "legacy"
    assert any("below required" in reason for reason in readiness.reasons)


def test_migration_readiness_serializes_for_api_response():
    readiness = evaluate_migration_readiness([
        _sample("device", "Device:Spine1", "Device:Spine1"),
    ])

    body = readiness_to_dict(readiness)

    assert body["ready"] is True
    assert body["samples"][0]["sample_id"] == "device"
    assert body["rollback_engine"] == "legacy"