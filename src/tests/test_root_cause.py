from datetime import datetime, timezone

import networkx as nx
import pytest

from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
from topology_syslog.node_monitor.models import NodeState, NodeStateRecord
from topology_syslog.models import SyslogMessage
from topology_syslog.topology.graph_engine import GraphEngine


def _msg(hostname: str, message: str = "test event") -> SyslogMessage:
    return SyslogMessage(
        received_at=datetime.now(tz=timezone.utc),
        source_ip="10.0.0.1",
        hostname=hostname,
        facility=3,
        severity=3,
        message=message,
    )


def test_3node_chain_single_incident(poc_engine):
    msgs = [
        _msg("Core-Router1", "%LINK-3-UPDOWN: Interface GE0/0 down"),
        _msg("Dist-Switch1",  "%BGP-5-ADJCHANGE: neighbor down"),
        _msg("Access-SW1",    "%PING-3-FAILED: gateway unreachable"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.root_cause_node == "Core-Router1"
    assert set(inc.secondary_nodes) == {"Dist-Switch1", "Access-SW1"}
    assert inc.raw_log_count == 3
    assert inc.status == "OPEN"


def test_noise_separation_yields_two_incidents(poc_engine):
    msgs = [
        _msg("Core-Router1", "%LINK-3-UPDOWN: Interface GE0/0 down"),
        _msg("Dist-Switch1",  "%BGP-5-ADJCHANGE: neighbor down"),
        _msg("Access-SW1",    "%PING-3-FAILED: gateway unreachable"),
        _msg("Branch-Router2", "%LINK-3-UPDOWN: WAN interface down"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert len(incidents) == 2
    root_causes = {i.root_cause_node for i in incidents}
    assert "Core-Router1" in root_causes
    assert "Branch-Router2" in root_causes


def test_branch_chain_secondary(poc_engine):
    """Branch-Router2 と Branch-Access-SW1 が連鎖する場合。"""
    msgs = [
        _msg("Branch-Router2",    "%LINK-3-UPDOWN: WAN down"),
        _msg("Branch-Access-SW1", "%CDP-4-NATIVE_VLAN_MISMATCH: vlan mismatch"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Branch-Router2"
    assert incidents[0].secondary_nodes == ["Branch-Access-SW1"]


def test_unknown_host_excluded(poc_engine):
    msgs = [
        _msg("Core-Router1", "link down"),
        _msg("UnknownDevice", "some error"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert all(i.root_cause_node != "UnknownDevice" for i in incidents)
    assert all("UnknownDevice" not in i.secondary_nodes for i in incidents)


def test_empty_messages_returns_empty(poc_engine):
    assert RootCauseInferencer().infer([], poc_engine) == []


def test_all_unknown_returns_empty(poc_engine):
    msgs = [_msg("Ghost1"), _msg("Ghost2")]
    assert RootCauseInferencer().infer(msgs, poc_engine) == []


def test_incident_id_format(poc_engine):
    msgs = [_msg("Core-Router1", "link down")]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert incidents[0].incident_id.startswith("INC-")
    parts = incidents[0].incident_id.split("-")
    assert len(parts) == 3
    assert parts[1].isdigit() and len(parts[1]) == 8  # YYYYMMDD
    assert parts[2].isdigit() and len(parts[2]) == 3  # NNN


def test_incident_counter_increments(poc_engine):
    inferencer = RootCauseInferencer()
    msgs = [_msg("Core-Router1", "down")]
    id1 = inferencer.infer(msgs, poc_engine)[0].incident_id
    id2 = inferencer.infer(msgs, poc_engine)[0].incident_id
    assert id1 != id2
    assert int(id2.split("-")[2]) == int(id1.split("-")[2]) + 1


# ---------------------------------------------------------------------------
# Phase 8-1: タイムスタンプ優先度
# ---------------------------------------------------------------------------

def _msg_at(hostname: str, received_at: datetime, message: str = "test event") -> SyslogMessage:
    return SyslogMessage(
        received_at=received_at,
        source_ip="10.0.0.1",
        hostname=hostname,
        facility=3,
        severity=3,
        message=message,
    )


def test_earlier_timestamp_root_cause_listed_first(poc_engine):
    """タイムスタンプが早い根本原因が先に出力される"""
    t1 = datetime(2026, 8, 17, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 17, 10, 0, 5, tzinfo=timezone.utc)
    # Branch-Router2 を先に、Core-Router1 を後に渡してもタイムスタンプで並ぶ
    msgs = [
        _msg_at("Branch-Router2", t2, "%LINK-3-UPDOWN: down"),
        _msg_at("Core-Router1",   t1, "%LINK-3-UPDOWN: down"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert len(incidents) == 2
    assert incidents[0].root_cause_node == "Core-Router1"    # t1 が早い
    assert incidents[1].root_cause_node == "Branch-Router2"  # t2 が遅い


def test_upstream_node_still_wins_regardless_of_timestamp(poc_engine):
    """Leaf が先に届いても上流 Core-Router1 が根本原因になる（タイムスタンプは順序のみ）"""
    t1 = datetime(2026, 8, 17, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 17, 10, 0, 3, tzinfo=timezone.utc)
    msgs = [
        _msg_at("Dist-Switch1", t1, "%BGP-5-ADJCHANGE: neighbor down"),  # 先着
        _msg_at("Core-Router1", t2, "%LINK-3-UPDOWN: down"),              # 後着
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Core-Router1"  # 上流優先は変わらない


# ---------------------------------------------------------------------------
# Phase 8-2: Severity フィルター
# ---------------------------------------------------------------------------

def test_low_severity_message_excluded_from_inference(poc_engine):
    """severity > threshold のメッセージは推論に使われず独立インシデントにならない"""
    # severity=6 (INFO) は推論対象外
    msgs = [
        _msg("Core-Router1", "%LINK-3-UPDOWN: down"),           # severity=3 (ERROR) → 対象
        SyslogMessage(
            received_at=datetime.now(tz=timezone.utc),
            source_ip="10.0.0.2",
            hostname="Branch-Router2",
            facility=3,
            severity=6,  # INFO — 閾値 5 (NOTICE) を超えるため除外
            message="%SYS-6-LOGGINGHOST_STARTSTOP: info message",
        ),
    ]
    inferencer = RootCauseInferencer(severity_threshold=5)
    incidents = inferencer.infer(msgs, poc_engine)
    roots = {i.root_cause_node for i in incidents}
    # Branch-Router2 は INFO ログのみなので推論対象外 → インシデントにならない
    assert "Branch-Router2" not in roots
    assert "Core-Router1" in roots


def test_low_severity_message_appears_in_raw_logs(poc_engine):
    """severity > threshold のメッセージでも raw_logs には記録される"""
    low_sev_msg = SyslogMessage(
        received_at=datetime.now(tz=timezone.utc),
        source_ip="10.0.0.1",
        hostname="Core-Router1",
        facility=3,
        severity=7,  # DEBUG
        message="%SYS-7-DEBUG: debug info",
    )
    high_sev_msg = _msg("Core-Router1", "%LINK-3-UPDOWN: Interface down")  # severity=3
    inferencer = RootCauseInferencer(severity_threshold=5)
    incidents = inferencer.infer([low_sev_msg, high_sev_msg], poc_engine)
    assert len(incidents) == 1
    raw = incidents[0].raw_logs
    # DEBUG メッセージも raw_logs には含まれる
    assert any("debug info" in log for log in raw)


def test_all_messages_below_threshold_yields_no_incidents(poc_engine):
    """全メッセージが閾値を超えると（全 INFO）インシデントが生成されない"""
    msgs = [
        SyslogMessage(
            received_at=datetime.now(tz=timezone.utc),
            source_ip="10.0.0.1",
            hostname="Core-Router1",
            facility=3,
            severity=6,
            message="%SYS-6-INFO: informational",
        )
    ]
    assert RootCauseInferencer(severity_threshold=5).infer(msgs, poc_engine) == []


# ---------------------------------------------------------------------------
# Phase 8-4: サイレントセカンダリ推論
# ---------------------------------------------------------------------------

def _spine_leaf_engine(n_leaves: int = 3) -> GraphEngine:
    """Spine1 → Leaf1..Leafn の星型グラフ（Spine1 はログ送信不可を想定）。"""
    g = nx.DiGraph()
    g.add_node("Spine1", role="spine")
    for i in range(1, n_leaves + 1):
        leaf = f"Leaf{i}"
        g.add_node(leaf, role="leaf")
        g.add_edge("Spine1", leaf, edge_type="physical")
    return GraphEngine(g)


def test_silent_root_cause_inferred_when_upstream_crashes():
    """上流がクラッシュして全配下が BGP ログを出したとき、上流がサイレント根本原因になる"""
    engine = _spine_leaf_engine(3)
    msgs = [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf3", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ]
    incidents = RootCauseInferencer().infer(msgs, engine)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.root_cause_node == "Spine1"
    assert set(inc.secondary_nodes) == {"Leaf1", "Leaf2", "Leaf3"}
    assert inc.primary_event == "(inferred \u2014 node did not send SYSLOG)"


def test_silent_inference_not_triggered_for_single_leaf():
    """配下が 1 台のみでは閾値を超えずサイレント推論は発動しない"""
    engine = _spine_leaf_engine(1)
    msgs = [_msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor down")]
    incidents = RootCauseInferencer().infer(msgs, engine)
    # Leaf1 が独立インシデントになり、Spine1 はサイレント根本原因にならない
    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Leaf1"


def test_silent_root_cause_inferred_from_single_leaf_named_peer():
    """単一 Leaf でも、BGP ログで無発報の上流 peer が特定できれば推論する。"""
    g = nx.DiGraph()
    g.add_node("Spine2", role="spine", addresses={"10.2.11.1"})
    g.add_node("Leaf1", role="leaf")
    g.add_edge("Spine2", "Leaf1", edge_type="physical")
    engine = GraphEngine(g)

    incidents = RootCauseInferencer().infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.2.11.1 Down"),
    ], engine)

    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Spine2"
    assert incidents[0].secondary_nodes == ["Leaf1"]
    assert incidents[0].primary_event == "(inferred \u2014 node did not send SYSLOG)"


def test_silent_leaf_inferred_from_spines_reporting_named_peer_down():
    """複数 Spine が無発報の直接隣接 Leaf を Down と報告した場合も推論する。"""
    g = nx.DiGraph()
    g.add_node("Spine1", role="spine")
    g.add_node("Spine2", role="spine")
    g.add_node("Leaf2", role="leaf", addresses={"10.1.12.2", "10.2.12.2"})
    g.add_edge("Spine1", "Leaf2", edge_type="physical")
    g.add_edge("Spine2", "Leaf2", edge_type="physical")
    engine = GraphEngine(g)

    incidents = RootCauseInferencer().infer([
        _msg("Spine1", "%BGP-5-ADJCHANGE: neighbor 10.1.12.2 Down"),
        _msg("Spine2", "%BGP-5-ADJCHANGE: neighbor 10.2.12.2 Down"),
    ], engine)

    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Leaf2"
    assert incidents[0].secondary_nodes == ["Spine1", "Spine2"]
    assert incidents[0].primary_event == "(inferred \u2014 node did not send SYSLOG)"


class _NodeStateReader:
    def __init__(self, state: NodeState) -> None:
        self._state = state

    def get(self, node_id: str, *, now=None) -> NodeStateRecord:
        observed_at = datetime.now(tz=timezone.utc)
        return NodeStateRecord(
            node_id=node_id,
            state=self._state,
            observed_at=observed_at,
            expires_at=observed_at,
            reason="test monitor result",
        )


def _single_leaf_peer_engine() -> GraphEngine:
    g = nx.DiGraph()
    g.add_node("Spine2", role="spine", addresses={"10.2.11.1"})
    g.add_node("Leaf1", role="leaf")
    g.add_edge("Spine2", "Leaf1", edge_type="physical")
    return GraphEngine(g)


def test_down_peer_adds_node_monitor_evidence_and_confidence():
    incidents = RootCauseInferencer(node_state_reader=_NodeStateReader(NodeState.DOWN)).infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.2.11.1 Down"),
    ], _single_leaf_peer_engine())

    incident = incidents[0]
    assert incident.root_cause_node == "Spine2"
    assert incident.rca_explanation.confidence == 0.75
    assert any(evidence.source == "node-monitor" for evidence in incident.rca_explanation.primary_candidate.evidences)


def test_explicit_bgp_down_peer_becomes_silent_root_cause_even_if_monitor_is_up():
    incidents = RootCauseInferencer(node_state_reader=_NodeStateReader(NodeState.UP)).infer([
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor 10.2.11.1 Down"),
    ], _single_leaf_peer_engine())

    assert incidents[0].root_cause_node == "Spine2"


def test_monitored_down_leaf_is_prioritized_over_spine_bgp_candidate():
    g = nx.DiGraph()
    g.add_node("Spine2", role="spine", addresses={"10.2.12.1"})
    g.add_node("Leaf2", role="leaf", addresses={"10.2.12.2"})
    g.add_edge("Spine2", "Leaf2", edge_type="physical")
    engine = GraphEngine(g)

    class _Leaf2DownReader:
        def get(self, node_id: str, *, now=None) -> NodeStateRecord:
            observed_at = datetime.now(tz=timezone.utc)
            state = NodeState.DOWN if node_id == "Leaf2" else NodeState.UP
            return NodeStateRecord(node_id, state, observed_at, observed_at, "test monitor result")

    incidents = RootCauseInferencer(node_state_reader=_Leaf2DownReader()).infer([
        _msg("Spine2", "%BGP-5-ADJCHANGE: neighbor down"),
    ], engine)

    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.root_cause_node == "Leaf2"
    assert incident.secondary_nodes == ["Spine2"]
    assert any(evidence.source == "node-monitor" for evidence in incident.rca_explanation.primary_candidate.evidences)


def test_silent_root_cause_coexists_with_independent_incident():
    """サイレント根本原因インシデントと独立インシデントが同一ウィンドウ内で共存する"""
    g = nx.DiGraph()
    g.add_node("Spine1",     role="spine")
    g.add_node("Leaf1",      role="leaf")
    g.add_node("Leaf2",      role="leaf")
    g.add_node("Standalone", role="leaf")
    g.add_edge("Spine1", "Leaf1", edge_type="physical")
    g.add_edge("Spine1", "Leaf2", edge_type="physical")
    engine = GraphEngine(g)

    msgs = [
        _msg("Leaf1",      "%BGP-5-ADJCHANGE: neighbor down"),
        _msg("Leaf2",      "%BGP-5-ADJCHANGE: neighbor down"),
        _msg("Standalone", "%LINK-3-UPDOWN: interface down"),  # 独立障害
    ]
    incidents = RootCauseInferencer().infer(msgs, engine)
    roots = {i.root_cause_node for i in incidents}
    assert "Spine1" in roots       # サイレント根本原因
    assert "Standalone" in roots   # 独立インシデント
    assert len(incidents) == 2


def test_normal_logging_upstream_prevents_silent_inference():
    """上流自身もログを出しているとき（通常障害）、サイレント推論は発動しない"""
    engine = _spine_leaf_engine(3)
    msgs = [
        _msg("Spine1", "%LINK-3-UPDOWN: Interface down"),         # 上流もログあり
        _msg("Leaf1",  "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2",  "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf3",  "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ]
    incidents = RootCauseInferencer().infer(msgs, engine)
    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Spine1"
    # 通常集約なのでサイレントイベント文字列は使われない
    assert incidents[0].primary_event != "(inferred \u2014 node did not send SYSLOG)"


# ---------------------------------------------------------------------------
# Phase 8-3: フラッピング検出
# ---------------------------------------------------------------------------

def test_flapping_detected_when_same_event_repeated():
    """同一ノードで同一 %FAC-SEV-MNEM が閾値回以上 → FLAPPING インシデント"""
    engine = _spine_leaf_engine(1)
    msgs = [
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface Gi0/0 changed state to down"),
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface Gi0/0 changed state to up"),
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface Gi0/0 changed state to down"),
    ]
    incidents = RootCauseInferencer(flapping_threshold=3).infer(msgs, engine)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.root_cause_node == "Leaf1"
    assert inc.status == "OPEN"
    assert inc.condition == "FLAPPING"
    assert "%LINK-3-UPDOWN" in inc.primary_event
    assert "3x" in inc.primary_event


def test_flapping_not_triggered_below_threshold():
    """同一イベントが閾値未満のときは FLAPPING にならない"""
    engine = _spine_leaf_engine(1)
    msgs = [
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface Gi0/0 changed state to down"),
        _msg("Leaf1", "%LINK-3-UPDOWN: Interface Gi0/0 changed state to up"),
    ]
    incidents = RootCauseInferencer(flapping_threshold=3).infer(msgs, engine)
    # 2 回は閾値 3 未満 → 通常インシデント（ただしメッセージが active_nodes に含まれる）
    assert all(i.condition != "FLAPPING" for i in incidents)


def test_flapping_node_excluded_from_regular_inference():
    """フラッピングノードは通常の根本原因推論から除外される"""
    g = nx.DiGraph()
    g.add_node("Router1", role="core")
    g.add_node("Switch1", role="access")
    g.add_edge("Router1", "Switch1", edge_type="physical")
    engine = GraphEngine(g)

    msgs = [
        # Router1 は安定した障害（1回）
        _msg("Router1", "%LINK-3-UPDOWN: Interface down"),
        # Switch1 はフラッピング（3回）
        _msg("Switch1", "%LINK-3-UPDOWN: Interface Gi0/1 down"),
        _msg("Switch1", "%LINK-3-UPDOWN: Interface Gi0/1 up"),
        _msg("Switch1", "%LINK-3-UPDOWN: Interface Gi0/1 down"),
    ]
    incidents = RootCauseInferencer(flapping_threshold=3).infer(msgs, engine)
    conditions = {i.root_cause_node: i.condition for i in incidents}
    statuses = {i.root_cause_node: i.status for i in incidents}
    # Switch1 は FLAPPING condition
    assert conditions.get("Switch1") == "FLAPPING"
    # Router1 は通常インシデント（Switch1 を secondary として持たない）
    router_inc = next(i for i in incidents if i.root_cause_node == "Router1")
    assert router_inc.status == "OPEN"
    assert router_inc.condition == "ACTIVE"
    assert "Switch1" not in router_inc.secondary_nodes


# ---------------------------------------------------------------------------
# BGP エッジの有効化ルール
# ---------------------------------------------------------------------------

def _bgp_engine() -> GraphEngine:
    """Leaf1 --physical--> Spine1、Leaf1 --BGP--> Leaf2 のグラフ。"""
    g = nx.DiGraph()
    g.add_node("Spine1", role="spine")
    g.add_node("Leaf1",  role="leaf")
    g.add_node("Leaf2",  role="leaf")
    g.add_edge("Spine1", "Leaf1", edge_type="physical")
    g.add_edge("Leaf1",  "Leaf2", edge_type="bgp")
    return GraphEngine(g)


def test_bgp_edge_active_when_both_nodes_have_bgp_syslog():
    """両ノードが BGP ログを持つとき、BGP エッジ経由で1インシデントに集約される"""
    engine = _bgp_engine()
    msgs = [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor down"),
        _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor down"),
    ]
    incidents = RootCauseInferencer().infer(msgs, engine)
    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Leaf1"
    assert "Leaf2" in incidents[0].secondary_nodes


def test_bgp_edge_inactive_when_destination_has_non_bgp_syslog():
    """Leaf2 が BGP 以外のログのみの場合、BGP エッジは無効 → 独立インシデント"""
    engine = _bgp_engine()
    msgs = [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor down"),
        _msg("Leaf2", "%SYS-5-CONFIG_I: configured from console"),
    ]
    incidents = RootCauseInferencer().infer(msgs, engine)
    assert len(incidents) == 2
    roots = {i.root_cause_node for i in incidents}
    assert roots == {"Leaf1", "Leaf2"}


def test_physical_failure_cascades_through_bgp_when_bgp_syslog_present():
    """物理障害 → BGP セッション断が連鎖するとき、1インシデントに集約される"""
    engine = _bgp_engine()
    msgs = [
        _msg("Spine1", "%LINK-3-UPDOWN: Interface down"),
        _msg("Leaf1",  "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2",  "%BGP-5-ADJCHANGE: neighbor Leaf1 down"),
    ]
    incidents = RootCauseInferencer().infer(msgs, engine)
    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Spine1"
    assert set(incidents[0].secondary_nodes) == {"Leaf1", "Leaf2"}


def test_inferencer_attaches_rca_explanation_to_incident():
    engine = _spine_leaf_engine(2)
    msgs = [
        _msg("Spine1", "%LINK-3-UPDOWN: Interface down"),
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ]

    incident = RootCauseInferencer().infer(msgs, engine)[0]

    explanation = incident.rca_explanation
    assert explanation.primary_candidate is not None
    assert explanation.primary_candidate.node_id == "Spine1"
    assert explanation.primary_candidate.secondary_nodes == ["Leaf1", "Leaf2"]
    assert {evidence.source for evidence in explanation.primary_candidate.evidences} >= {"syslog", "topology"}
    assert {candidate.node_id for candidate in explanation.alternative_candidates} == {"Leaf1", "Leaf2"}


def test_silent_root_rca_explanation_uses_topology_evidence():
    engine = _spine_leaf_engine(2)
    msgs = [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ]

    incident = RootCauseInferencer().infer(msgs, engine)[0]

    explanation = incident.rca_explanation
    assert explanation.primary_candidate is not None
    assert explanation.primary_candidate.node_id == "Spine1"
    assert any("common upstream ancestor" in evidence.summary for evidence in explanation.primary_candidate.evidences)


def test_rca_confidence_scores_topology_and_syslog_evidence():
    engine = _spine_leaf_engine(2)
    msgs = [
        _msg("Spine1", "%LINK-3-UPDOWN: Interface down"),
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ]

    incident = RootCauseInferencer().infer(msgs, engine)[0]
    explanation = incident.rca_explanation

    assert explanation.confidence == 0.65
    assert explanation.primary_candidate.confidence == 0.65
    assert {evidence.weight for evidence in explanation.primary_candidate.evidences} >= {0.30, 0.20, 0.15}


def test_silent_root_confidence_is_medium_but_not_zero():
    engine = _spine_leaf_engine(2)
    msgs = [
        _msg("Leaf1", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
        _msg("Leaf2", "%BGP-5-ADJCHANGE: neighbor Spine1 down"),
    ]

    incident = RootCauseInferencer().infer(msgs, engine)[0]

    assert incident.rca_explanation.confidence == 0.45
    assert all(candidate.confidence > 0 for candidate in incident.rca_explanation.alternative_candidates)
