"""根本原因推論エンジン。

F-3.3 仕様に基づき、ウィンドウ内の SyslogMessage 群から
Incident リストを生成する。

BGP エッジはルーティングプロトコル関連のSYSLOGを持つノードに対してのみ有効。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from topology_syslog.models import Incident, SyslogMessage
from topology_syslog.topology.graph_engine import GraphEngine

# BGP エッジを有効化するルーティングプロトコル識別子
_ROUTING_PREFIXES: frozenset[str] = frozenset([
    "%BGP-", "%OSPF-", "%ISIS-", "%EIGRP-", "%RIP-",
])

# Cisco IOS %FAC-SEV-MNEM 抽出
_CISCO_EVENT_RE = re.compile(r'%[A-Z0-9_]+-\d+-[A-Z0-9_]+')


def _extract_event_type(message: str) -> str | None:
    m = _CISCO_EVENT_RE.search(message)
    return m.group(0) if m else None


def _is_routing_event(message: str) -> bool:
    return any(prefix in message for prefix in _ROUTING_PREFIXES)


# サイレント根本原因のプレースホルダーイベント
_SILENT_EVENT = "(inferred — node did not send SYSLOG)"


def _split_by_time_gap(
    messages: list[SyslogMessage],
    gap_sec: int,
) -> list[list[SyslogMessage]]:
    """received_at のギャップが gap_sec 秒を超える箇所でメッセージを分割する。"""
    if not messages:
        return []
    sorted_msgs = sorted(messages, key=lambda m: m.received_at)
    clusters: list[list[SyslogMessage]] = [[sorted_msgs[0]]]
    for msg in sorted_msgs[1:]:
        gap = (msg.received_at - clusters[-1][-1].received_at).total_seconds()
        if gap > gap_sec:
            clusters.append([])
        clusters[-1].append(msg)
    return clusters


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


class RootCauseInferencer:
    def __init__(
        self,
        severity_threshold: int = 5,
        silent_coverage: float = 0.6,
        flapping_threshold: int = 3,
        gap_sec: int = 0,
    ) -> None:
        self._counters: dict[str, int] = {}
        # 0=EMERG…5=NOTICE を推論対象、6=INFO / 7=DEBUG は raw_logs のみ
        self._severity_threshold = severity_threshold
        self._silent_coverage = silent_coverage
        self._flapping_threshold = flapping_threshold
        # 0 = 無効（分割しない）
        self._gap_sec = gap_sec

    def infer(
        self,
        messages: list[SyslogMessage],
        graph: GraphEngine,
    ) -> list[Incident]:
        if self._gap_sec > 0:
            clusters = _split_by_time_gap(messages, self._gap_sec)
            if len(clusters) > 1:
                return [inc for cluster in clusters for inc in self.infer(cluster, graph)]

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
                ))
                assigned.add(node)

        # サイレント根本原因: ログを送れなかった上流ノードを正規処理の前に検出・集約
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
            ))

        return incidents

    def _new_id(self, date_str: str) -> str:
        n = self._counters.get(date_str, 0) + 1
        self._counters[date_str] = n
        return f"INC-{date_str}-{n:03d}"
