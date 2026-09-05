from datetime import datetime, timezone

from topology_syslog.correlation.hypothesis_scoring import HypothesisScorer
from topology_syslog.correlation.observation import Observation, ObservationNormalizer
from topology_syslog.models import SyslogMessage
from topology_syslog.topology.causal_topology import CausalTopology


def _msg(hostname: str, message: str) -> SyslogMessage:
    event_type = None
    if "%LINK-3-UPDOWN" in message:
        event_type = "%LINK-3-UPDOWN"
    elif "%BGP-5-ADJCHANGE" in message:
        event_type = "%BGP-5-ADJCHANGE"
    return SyslogMessage(
        received_at=datetime.now(tz=timezone.utc),
        source_ip="10.0.0.1",
        hostname=hostname,
        facility=3,
        severity=3,
        message=message,
        event_type=event_type,
    )


def _topology() -> CausalTopology:
    return CausalTopology.from_iida_topology({
        "network-model": {
            "physical-layer": {
                "device": [
                    {
                        "device-id": "Spine1",
                        "interface": [
                            {"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.1/30"},
                            {"interface-id": "GigabitEthernet0/1", "ip-address": "10.1.12.1/30"},
                        ],
                    },
                    {
                        "device-id": "Leaf1",
                        "interface": [{"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.11.2/30"}],
                    },
                    {
                        "device-id": "Leaf2",
                        "interface": [{"interface-id": "GigabitEthernet0/0", "ip-address": "10.1.12.2/30"}],
                    },
                ],
                "physical-connection": [
                    {
                        "connection-id": "Spine1-Leaf1",
                        "endpoint": [
                            {"device-id": "Spine1", "interface-id": "GigabitEthernet0/0"},
                            {"device-id": "Leaf1", "interface-id": "GigabitEthernet0/0"},
                        ],
                    },
                    {
                        "connection-id": "Spine1-Leaf2",
                        "endpoint": [
                            {"device-id": "Spine1", "interface-id": "GigabitEthernet0/1"},
                            {"device-id": "Leaf2", "interface-id": "GigabitEthernet0/0"},
                        ],
                    },
                ],
            },
            "layer3-layer": {
                "bgp-session": [
                    {
                        "session-id": "Spine1-Leaf1-eBGP",
                        "type": "ebgp",
                        "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf1"}],
                    },
                    {
                        "session-id": "Spine1-Leaf2-eBGP",
                        "type": "ebgp",
                        "endpoint": [{"device-id": "Spine1"}, {"device-id": "Leaf2"}],
                    },
                ],
            },
        }
    })


def _observations(topology: CausalTopology, messages: list[SyslogMessage]) -> tuple[Observation, ...]:
    normalizer = ObservationNormalizer(topology)
    return tuple(
        observation for message in messages
        if (observation := normalizer.normalize(message)) is not None
    )


def _component_map(hypothesis):
    return {component.name: component.value for component in hypothesis.score_components}


def test_scorer_exposes_score_components_for_best_hypothesis():
    topology = _topology()
    observations = _observations(topology, [
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
        _msg("Spine1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.1.11.1 down"),
    ])

    best = HypothesisScorer(topology).score(observations)[0]

    assert best.root_cause_object == "PhysicalLink:Leaf1:GigabitEthernet0/0--Spine1:GigabitEthernet0/0"
    assert set(_component_map(best)) == {
        "coverage",
        "specificity",
        "direct_evidence",
        "evidence_strength",
        "silent_peer",
        "temporal_fit",
        "contradiction",
        "redundancy",
        "link_coherence",
        "topology_distance",
    }
    assert _component_map(best)["coverage"] == 100.0
    assert _component_map(best)["link_coherence"] == 18.0
    assert _component_map(best)["topology_distance"] < 0


def test_scorer_prefers_device_when_it_explains_multiple_downstream_sessions():
    topology = _topology()
    observations = _observations(topology, [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ])

    assert HypothesisScorer(topology).score(observations)[0].root_cause_object == "Device:Spine1"


def test_scorer_keeps_single_interface_fault_local():
    topology = _topology()
    observations = _observations(topology, [
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
    ])

    assert HypothesisScorer(topology).score(observations)[0].root_cause_object == "Interface:Leaf1:GigabitEthernet0/0"


def test_scorer_keeps_single_bgp_fault_on_session():
    topology = _topology()
    observations = _observations(topology, [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ])

    assert HypothesisScorer(topology).score(observations)[0].root_cause_object == "BGPSession:Spine1-Leaf1-eBGP"


def test_scorer_tie_breaker_is_deterministic_for_equal_interface_faults():
    topology = _topology()
    observations = _observations(topology, [
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
        _msg("Leaf2", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
    ])

    roots = [
        hypothesis.root_cause_object
        for hypothesis in HypothesisScorer(topology).score(observations)
        if hypothesis.root_cause_object.startswith("Interface:")
    ][:2]

    assert roots == [
        "Interface:Leaf2:GigabitEthernet0/0",
        "Interface:Leaf1:GigabitEthernet0/0",
    ]


def test_confidence_uses_margin_coverage_and_direct_evidence():
    topology = _topology()
    scorer = HypothesisScorer(topology)
    link_observations = _observations(topology, [
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
        _msg("Spine1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.1.11.1 down"),
    ])
    ambiguous_observations = _observations(topology, [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ])

    assert scorer.confidence(scorer.score(link_observations)) > scorer.confidence(scorer.score(ambiguous_observations))
    assert 0.0 <= scorer.confidence(scorer.score(link_observations)) <= 1.0


def test_scorer_penalizes_recovery_as_contradicting_fault_hypothesis():
    topology = _topology()
    recovery = Observation(
        observed_at=datetime.now(tz=timezone.utc),
        source_node="Leaf1",
        observed_object="Interface:Leaf1:GigabitEthernet0/0",
        assertion="recovery",
        signature="%LINK-*-UPDOWN",
        severity=3,
        raw_message="%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up",
        confidence=0.95,
    )

    best = HypothesisScorer(topology).score((recovery,))[0]

    assert _component_map(best)["contradiction"] < 0


def test_scorer_penalizes_broad_device_hypothesis_when_redundant_sessions_remain_uncovered():
    topology = _topology()
    observations = _observations(topology, [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ])
    hypotheses = HypothesisScorer(topology).score(observations)
    device_hypothesis = next(hypothesis for hypothesis in hypotheses if hypothesis.root_cause_object == "Device:Spine1")

    assert _component_map(device_hypothesis)["redundancy"] < 0