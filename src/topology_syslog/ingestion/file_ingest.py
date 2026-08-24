"""ファイル・標準入力から SYSLOG を読み込んでインシデントへ変換するエンジン。

使い方:
  topology-syslog -i network-syslog.txt          # ファイル一括処理
  tail -f network-syslog.txt | topology-syslog -i # パイプ（ストリーミング）
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
from topology_syslog.ingestion.syslog_filter import SyslogFilter
from topology_syslog.ingestion.syslog_parser import parse
from topology_syslog.models import Incident, SyslogMessage
from topology_syslog.topology.graph_engine import GraphEngine

_logger = logging.getLogger(__name__)

_FILE_SOURCE_IP = "file"


def _parse_line(line: str) -> SyslogMessage | None:
    """1 行を SyslogMessage にパースする。空行・失敗時は None。"""
    line = line.strip()
    if not line:
        return None
    try:
        return parse(line.encode("utf-8", errors="replace"), _FILE_SOURCE_IP)
    except Exception:
        _logger.debug("parse failed: %r", line[:120])
        return None


def _group_by_window(
    messages: list[SyslogMessage],
    window_sec: int,
) -> list[list[SyslogMessage]]:
    """タイムスタンプ順にメッセージを window_sec 秒ごとのバケットへ分割する。"""
    if not messages:
        return []
    sorted_msgs = sorted(messages, key=lambda m: m.received_at)
    windows: list[list[SyslogMessage]] = []
    current: list[SyslogMessage] = [sorted_msgs[0]]
    window_start = sorted_msgs[0].received_at

    for msg in sorted_msgs[1:]:
        elapsed = (msg.received_at - window_start).total_seconds()
        if elapsed <= window_sec:
            current.append(msg)
        else:
            windows.append(current)
            current = [msg]
            window_start = msg.received_at

    windows.append(current)
    return windows


def _emit_incident(inc: Incident, output_json: bool) -> None:
    if output_json:
        print(
            json.dumps(
                {
                    "incident_id": inc.incident_id,
                    "created_at": inc.created_at.isoformat(),
                    "root_cause_node": inc.root_cause_node,
                    "primary_event": inc.primary_event,
                    "secondary_nodes": inc.secondary_nodes,
                    "raw_log_count": inc.raw_log_count,
                    "status": inc.status,
                    "recurrence_count": inc.recurrence_count,
                    "maintenance_plan_id": inc.maintenance_plan_id,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    else:
        lines = [
            f"[INCIDENT] {inc.incident_id}",
            f"  Root Cause  : {inc.root_cause_node}",
            f"  Event       : {inc.primary_event}",
        ]
        if inc.secondary_nodes:
            lines.append(f"  Secondary   : {', '.join(inc.secondary_nodes)}")
        lines.append(f"  Logs        : {inc.raw_log_count}")
        lines.append(f"  Status      : {inc.status}")
        if inc.maintenance_plan_id:
            lines.append(f"  Maintenance : {inc.maintenance_plan_id}")
        print("\n".join(lines), flush=True)


def _process_window(
    msgs: list[SyslogMessage],
    graph: GraphEngine,
    inferencer: RootCauseInferencer,
    syslog_filter: SyslogFilter | None,
    output_json: bool,
    store: object,  # IncidentStore | None — 型循環を避けるため object
    maintenance_checker: object = None,  # MaintenanceChecker | None
) -> list[Incident]:
    """ウィンドウ内メッセージを推論してインシデントを返す。"""
    filtered = [m for m in msgs if syslog_filter is None or not syslog_filter.is_ignored(m)]
    non_recovery = [m for m in filtered if not m.is_recovery]
    if not non_recovery:
        return []

    try:
        incidents = inferencer.infer(non_recovery, graph)
    except Exception:
        _logger.exception("inference error")
        return []

    # ウィンドウ内の最小タイムスタンプを基準に判定（過去ログ処理でも正しい時刻で判定できる）
    window_at = min(m.received_at for m in filtered)

    for inc in incidents:
        if maintenance_checker is not None:
            plan = maintenance_checker.find_active_plan(inc, at=window_at, graph=graph)
            if plan is not None:
                inc.status = "CLOSED"
                inc.maintenance_plan_id = plan.plan_id
                _logger.info(
                    "Auto-closed %s (root_cause=%s): matches maintenance plan %s",
                    inc.incident_id, inc.root_cause_node, plan.plan_id,
                )
        if store is not None:
            try:
                inc.recurrence_count = store.count_by_root_cause(inc.root_cause_node)
                store.save(inc)
            except Exception:
                _logger.warning("Failed to save incident %s", inc.incident_id)
        _emit_incident(inc, output_json)

    return incidents


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_batch(
    file_path: str,
    graph: GraphEngine,
    inferencer: RootCauseInferencer,
    *,
    syslog_filter: SyslogFilter | None = None,
    window_sec: int = 30,
    output_json: bool = False,
    store: object = None,
    maintenance_checker: object = None,
) -> int:
    """ファイルを一括処理してインシデント総数を返す。"""
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    messages = [m for line in text.splitlines() if (m := _parse_line(line)) is not None]
    _logger.info("Parsed %d syslog line(s) from %s", len(messages), file_path)

    windows = _group_by_window(messages, window_sec)
    _logger.info("Grouped into %d time window(s) of %ds", len(windows), window_sec)

    total = 0
    for window in windows:
        total += len(_process_window(window, graph, inferencer, syslog_filter, output_json, store, maintenance_checker))
    return total


async def run_stream(
    graph: GraphEngine,
    inferencer: RootCauseInferencer,
    *,
    syslog_filter: SyslogFilter | None = None,
    window_sec: int = 30,
    output_json: bool = False,
    store: object = None,
    maintenance_checker: object = None,
) -> int:
    """標準入力をストリーミング読み込みしてインシデントを処理する。

    window_sec 秒間新規行が来なければバッファをフラッシュして推論する。
    EOF でも残バッファをフラッシュする。
    """
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    buffer: list[SyslogMessage] = []
    total = 0

    async def _flush() -> None:
        nonlocal total
        if not buffer:
            return
        msgs = buffer.copy()
        buffer.clear()
        total += len(_process_window(msgs, graph, inferencer, syslog_filter, output_json, store, maintenance_checker))

    while True:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=float(window_sec))
        except asyncio.TimeoutError:
            await _flush()
            continue

        if not raw:  # EOF
            await _flush()
            break

        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        msg = _parse_line(line)
        if msg is not None:
            buffer.append(msg)

    return total
