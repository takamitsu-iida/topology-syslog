"""根本原因推論エンジン。

F-3.3 仕様に基づき、ウィンドウ内の SyslogMessage 群から
Incident リストを生成する。

BGP エッジはルーティングプロトコル関連のSYSLOGを持つノードに対してのみ有効。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from topology_syslog.correlation.confidence import score_rca_explanation
from topology_syslog.models import Incident, RCAEvidence, RCAExplanation, RCACandidate, SyslogMessage
from topology_syslog.node_monitor.models import NodeState, NodeStateRecord
from topology_syslog.node_monitor.store import NodeStateReader
from topology_syslog.topology.graph_engine import GraphEngine

# BGP エッジを有効化するルーティングプロトコル識別子
_ROUTING_PREFIXES: frozenset[str] = frozenset([
    "%BGP", "%OSPF-", "%ISIS-", "%EIGRP-", "%RIP-",
])

# Cisco IOS %FAC-SEV-MNEM 抽出
_CISCO_EVENT_RE = re.compile(r'%[A-Z0-9_]+-\d+-[A-Z0-9_]+')
_BGP_NEIGHBOR_LOST_RE = re.compile(
    r'\b(?:sent\s+to\s+neighbor|neighbor)\s+(\S+)(?:\s+\S+){0,6}?\s+(?:down\b|reset\b|\(?hold\s+time\s+expired\)?|topology\s+\S+\s+removed\s+from\s+session\b)',
    re.IGNORECASE,
)


def _extract_event_type(message: str) -> str | None:
    m = _CISCO_EVENT_RE.search(message)
    return m.group(0) if m else None


def _is_routing_event(message: str) -> bool:
    return any(prefix in message for prefix in _ROUTING_PREFIXES)


# サイレント根本原因のプレースホルダーイベント
_SILENT_EVENT = "(inferred — node did not send SYSLOG)"


def _detect_flapping(
    active: list[SyslogMessage],
    active_nodes: set[str],
    threshold: int,
) -> dict[str, tuple[str, int]]:
    """同一ノード × 同一 %FAC-SEV-MNEM が threshold 回以上のノードを返す。

    返値: {node: (event_type, count)}  ← カウント最大のイベント種別を代表値として採用。
    """
    counts: Counter = Counter(
        (m.hostname, et)
        for m in active
        if m.hostname in active_nodes
        for et in (_extract_event_type(m.message),)
        if et is not None
    )
    flapping: dict[str, tuple[str, int]] = {}
    for (node, et), cnt in counts.items():
        if cnt >= threshold and (node not in flapping or cnt > flapping[node][1]):
            flapping[node] = (et, cnt)
    return flapping


def _find_silent_root_candidates(
    active_nodes: set[str],
    graph: "GraphEngine",
    bgp_nodes: frozenset[str],
    min_coverage: float,
) -> list[str]:
    """active_nodes の共通祖先でログを出していないノードをカバレッジ降順で返す。

    物理エッジのみを辿る（BGP 経由の祖先は物理クラッシュ検出に不適切なため除外）。
    """
    if len(active_nodes) < 2:
        return []
    # frozenset() を渡すと get_ancestors_filtered は物理エッジのみ辿る
    coverage: dict[str, int] = {}
    for node in active_nodes:
        for ancestor in graph.get_ancestors_filtered(node, frozenset()):
            if ancestor not in active_nodes:
                coverage[ancestor] = coverage.get(ancestor, 0) + 1
    threshold = max(2, int(len(active_nodes) * min_coverage))
    return [
        n for n, cnt in sorted(coverage.items(), key=lambda x: -x[1])
        if cnt >= threshold
    ]


def _find_explicit_silent_root_candidates(
    active: list[SyslogMessage],
    active_nodes: set[str],
    graph: GraphEngine,
) -> dict[str, set[str]]:
    """BGP peer loss で明示された、無発報の直接隣接 peer を返す。"""
    candidates: dict[str, set[str]] = {}
    for message in active:
        if "interface flap" in message.message.lower():
            continue
        match = _BGP_NEIGHBOR_LOST_RE.search(message.message)
        if match is None:
            continue
        peer = graph.find_node_by_address(match.group(1))
        if peer is None or peer in active_nodes:
            continue
        if peer in graph.get_direct_neighbors(message.hostname):
            candidates.setdefault(peer, set()).add(message.hostname)
    return candidates


def _find_monitored_down_root_candidates(
    active_nodes: set[str],
    graph: GraphEngine,
    node_state_reader: NodeStateReader | None,
) -> dict[str, set[str]]:
    if node_state_reader is None:
        return {}
    related_nodes: set[str] = set()
    for node in active_nodes:
        related_nodes.update(graph.get_direct_neighbors(node))
    candidates: dict[str, set[str]] = {}
    for node in sorted(related_nodes):
        if node_state_reader.get(node).state != NodeState.DOWN:
            continue
        candidates[node] = {
            active_node for active_node in active_nodes
            if node in graph.get_direct_neighbors(active_node)
        }
    return candidates


def _build_rca_explanation(
    root_cause_node: str,
    secondary_nodes: list[str],
    messages: list[SyslogMessage],
    graph: GraphEngine,
    bgp_nodes: frozenset[str],
    *,
    silent: bool = False,
    flapping: bool = False,
    node_state: NodeStateRecord | None = None,
) -> RCAExplanation:
    evidences: list[RCAEvidence] = []
    root_log_ids = [str(idx) for idx, msg in enumerate(messages) if msg.hostname == root_cause_node]
    related_nodes = [root_cause_node, *secondary_nodes]

    if silent:
        evidences.append(RCAEvidence(
            source="topology",
            summary=f"{root_cause_node} is a common upstream ancestor of logged downstream nodes",
            weight=0.0,
            related_nodes=related_nodes,
            related_log_ids=[str(idx) for idx, msg in enumerate(messages) if msg.hostname in secondary_nodes],
        ))
    elif flapping:
        evidences.append(RCAEvidence(
            source="syslog",
            summary=f"{root_cause_node} emitted repeated matching events",
            weight=0.0,
            related_nodes=[root_cause_node],
            related_log_ids=root_log_ids,
        ))
    else:
        evidences.append(RCAEvidence(
            source="syslog",
            summary=f"{root_cause_node} emitted a root-cause candidate syslog message",
            weight=0.0,
            related_nodes=[root_cause_node],
            related_log_ids=root_log_ids,
        ))

    if secondary_nodes:
        evidences.append(RCAEvidence(
            source="topology",
            summary=f"{len(secondary_nodes)} logged node(s) are downstream of {root_cause_node}",
            weight=0.0,
            related_nodes=related_nodes,
            related_log_ids=[str(idx) for idx, msg in enumerate(messages) if msg.hostname in secondary_nodes],
        ))

    if node_state is not None and node_state.state == NodeState.DOWN:
        evidences.append(RCAEvidence(
            source="node-monitor",
            summary=f"{root_cause_node} is DOWN according to node monitor: {node_state.reason}",
            weight=0.0,
            related_nodes=[root_cause_node],
        ))

    upstream_logged = sorted(
        graph.get_ancestors_filtered(root_cause_node, bgp_nodes).intersection({msg.hostname for msg in messages})
    )
    if not upstream_logged and not silent:
        evidences.append(RCAEvidence(
            source="topology",
            summary=f"No logged upstream ancestor was found for {root_cause_node}",
            weight=0.0,
            related_nodes=[root_cause_node],
            related_log_ids=root_log_ids,
        ))

    primary = RCACandidate(
        node_id=root_cause_node,
        confidence=0.0,
        evidences=evidences,
        secondary_nodes=secondary_nodes,
    )
    alternatives = [
        RCACandidate(
            node_id=node,
            confidence=0.0,
            secondary_nodes=[],
            alternative_reason=f"{node} is downstream of selected root cause {root_cause_node}",
        )
        for node in secondary_nodes
    ]
    return score_rca_explanation(RCAExplanation(
        confidence=primary.confidence,
        primary_candidate=primary,
        alternative_candidates=alternatives,
    ), messages)


class RootCauseInferencer:
    def __init__(
        self,
        severity_threshold: int = 5,
        silent_coverage: float = 0.6,
        flapping_threshold: int = 3,
        node_state_reader: NodeStateReader | None = None,
    ) -> None:
        self._counters: dict[str, int] = {}
        # 0=EMERG…5=NOTICE を推論対象、6=INFO / 7=DEBUG は raw_logs のみ
        self._severity_threshold = severity_threshold
        self._silent_coverage = silent_coverage
        self._flapping_threshold = flapping_threshold
        self._node_state_reader = node_state_reader

    def infer(
        self,
        messages: list[SyslogMessage],
        graph: GraphEngine,
    ) -> list[Incident]:
        logged_nodes = {m.hostname for m in messages if graph.node_exists(m.hostname)}
        if not logged_nodes:
            return []

        now = datetime.now(tz=timezone.utc)
        date_str = now.strftime("%Y%m%d")
        incidents: list[Incident] = []
        assigned: set[str] = set()

        # severity > threshold のメッセージは推論に使わない（raw_logs には全件含める）
        active = [m for m in messages if m.severity <= self._severity_threshold]
        active_nodes = {m.hostname for m in active if graph.node_exists(m.hostname)}
        if not active_nodes:
            return []

        # ルーティングイベントを持つノード: BGP エッジの有効化判定に使う
        bgp_nodes = frozenset(
            m.hostname for m in active
            if graph.node_exists(m.hostname) and _is_routing_event(m.message)
        )
        monitored_down_roots = _find_monitored_down_root_candidates(
            active_nodes, graph, self._node_state_reader
        )

        # ノードごとの最初のログ受信時刻
        first_seen: dict[str, datetime] = {}
        for m in active:
            if graph.node_exists(m.hostname):
                if m.hostname not in first_seen or m.received_at < first_seen[m.hostname]:
                    first_seen[m.hostname] = m.received_at

        # 上流ノードがログを出していない = 根本原因候補
        # 複数候補がある場合は最初に届いたログの時刻で昇順ソート（因果順序）
        root_causes = sorted(
            (n for n in active_nodes
             if not graph.get_ancestors_filtered(n, bgp_nodes).intersection(active_nodes)),
            key=lambda n: first_seen.get(n, now),
        )

        # node-monitor が直接関連ノードの DOWN を確認した場合は最優先する
        for src, covered_nodes in monitored_down_roots.items():
            covered = sorted(covered_nodes - assigned)
            related = {src, *covered}
            related_msgs = [m for m in messages if m.hostname in related]
            incidents.append(Incident(
                incident_id=self._new_id(date_str),
                created_at=now,
                root_cause_node=src,
                primary_event=_SILENT_EVENT,
                secondary_nodes=covered,
                raw_log_count=len(related_msgs),
                raw_logs=[m.message for m in related_msgs],
                status="OPEN",
                rca_explanation=_build_rca_explanation(
                    src,
                    covered,
                    related_msgs,
                    graph,
                    bgp_nodes,
                    silent=True,
                    node_state=self._node_state_reader.get(src),
                ),
            ))
            assigned.update(related)

        # フラッピング検出: 正規推論の前に処理して assigned に追加
        if self._flapping_threshold > 0:
            for node, (event_type, count) in sorted(
                _detect_flapping(active, active_nodes, self._flapping_threshold).items()
            ):
                node_msgs = [m for m in messages if m.hostname == node]
                incidents.append(Incident(
                    incident_id=self._new_id(date_str),
                    created_at=now,
                    root_cause_node=node,
                    primary_event=f"FLAPPING: {event_type} repeated {count}x in window",
                    secondary_nodes=[],
                    raw_log_count=len(node_msgs),
                    raw_logs=[m.message for m in node_msgs],
                    status="OPEN",
                    condition="FLAPPING",
                    rca_explanation=_build_rca_explanation(
                        node,
                        [],
                        node_msgs,
                        graph,
                        bgp_nodes,
                        flapping=True,
                    ),
                ))
                assigned.add(node)

        # サイレント根本原因: ログを送れなかった上流ノードを正規処理の前に検出・集約
        explicit_silent_roots = _find_explicit_silent_root_candidates(active, active_nodes, graph)
        for src, covered_nodes in sorted(explicit_silent_roots.items()):
            node_state = self._node_state_reader.get(src) if self._node_state_reader else None
            covered = sorted(covered_nodes - assigned)
            if not covered:
                continue
            related_msgs = [m for m in messages if m.hostname in set(covered)]
            incidents.append(Incident(
                incident_id=self._new_id(date_str),
                created_at=now,
                root_cause_node=src,
                primary_event=_SILENT_EVENT,
                secondary_nodes=covered,
                raw_log_count=len(related_msgs),
                raw_logs=[m.message for m in related_msgs],
                status="OPEN",
                rca_explanation=_build_rca_explanation(
                    src,
                    covered,
                    related_msgs,
                    graph,
                    bgp_nodes,
                    silent=True,
                    node_state=node_state,
                ),
            ))
            assigned.update(covered)

        for src in _find_silent_root_candidates(active_nodes, graph, bgp_nodes, self._silent_coverage):
            descendants = graph.get_descendants_filtered(src, bgp_nodes)
            covered = sorted((active_nodes.intersection(descendants)) - assigned)
            if len(covered) < 2:
                continue
            related_msgs = [m for m in messages if m.hostname in set(covered)]
            incidents.append(Incident(
                incident_id=self._new_id(date_str),
                created_at=now,
                root_cause_node=src,
                primary_event=_SILENT_EVENT,
                secondary_nodes=covered,
                raw_log_count=len(related_msgs),
                raw_logs=[m.message for m in related_msgs],
                status="OPEN",
                rca_explanation=_build_rca_explanation(
                    src,
                    covered,
                    related_msgs,
                    graph,
                    bgp_nodes,
                    silent=True,
                ),
            ))
            assigned.update(covered)

        for rc in root_causes:
            if rc in assigned:  # サイレント/フラッピング処理済みノードはスキップ
                continue
            descendants = graph.get_descendants_filtered(rc, bgp_nodes)
            secondary = sorted((active_nodes.intersection(descendants)) - assigned)
            related = {rc, *secondary}
            # raw_logs: 関連ノードの全メッセージ（閾値除外分も含む）
            related_msgs = [m for m in messages if m.hostname in related]
            active_related = [m for m in active if m.hostname in related]
            primary_msg = next(
                (m.message for m in active_related if m.hostname == rc), "N/A"
            )
            incidents.append(Incident(
                incident_id=self._new_id(date_str),
                created_at=now,
                root_cause_node=rc,
                primary_event=primary_msg,
                secondary_nodes=secondary,
                raw_log_count=len(related_msgs),
                raw_logs=[m.message for m in related_msgs],
                status="OPEN",
                rca_explanation=_build_rca_explanation(
                    rc,
                    secondary,
                    related_msgs,
                    graph,
                    bgp_nodes,
                ),
            ))
            assigned.add(rc)
            assigned.update(secondary)

        # 根本原因グループに属さない独立ノード
        for node in sorted(active_nodes - assigned):
            node_msgs = [m for m in messages if m.hostname == node]
            primary_msg = node_msgs[0].message if node_msgs else "N/A"
            incidents.append(Incident(
                incident_id=self._new_id(date_str),
                created_at=now,
                root_cause_node=node,
                primary_event=primary_msg,
                secondary_nodes=[],
                raw_log_count=len(node_msgs),
                raw_logs=[m.message for m in node_msgs],
                status="OPEN",
                rca_explanation=_build_rca_explanation(
                    node,
                    [],
                    node_msgs,
                    graph,
                    bgp_nodes,
                ),
            ))

        return incidents

    def _new_id(self, date_str: str) -> str:
        n = self._counters.get(date_str, 0) + 1
        self._counters[date_str] = n
        return f"INC-{date_str}-{n:03d}"
