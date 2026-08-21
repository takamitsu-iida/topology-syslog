"""インシデント調査エージェント — pyATS による情報収集 + LLM ReAct ループ。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from topology_syslog.investigation.models import InvestigationReport
from topology_syslog.investigation.tools import TOOL_DEFINITIONS, ToolDispatcher
from topology_syslog.models import Incident

_logger = logging.getLogger(__name__)

_MAX_TURNS = 8

_SYSTEM_PROMPT = """\
あなたはネットワーク障害調査の専門家AIエージェントです。
インシデント情報をもとに実際のネットワーク装置に接続して情報を収集し、障害の詳細と対応策をまとめてください。

## 調査の進め方
1. インシデント情報から根本原因ノードと影響範囲を把握する
2. get_topology_info で関連装置の役割・隣接ノードを確認する
3. run_commands で根本原因ノードから優先的に状態を取得する
   - BGP セッション: show ip bgp summary
   - インターフェース: show interfaces / show ip interface brief
   - ルーティング: show ip route
   - ログ: show logging
4. 必要に応じて隣接装置も確認する
5. 収集した情報を元に最終レポートを日本語でまとめる

## 制約
- コマンドは show / display のみ使用可（設定変更・リセット操作は不可）
- 調査は最大 8 ターンで完了させること
"""


def _incident_context(incident: Incident) -> str:
    lines = [
        f"インシデントID: {incident.incident_id}",
        f"根本原因ノード: {incident.root_cause_node}",
        f"主要イベント: {incident.primary_event}",
        f"ステータス: {incident.status} / {incident.condition}",
    ]
    if incident.secondary_nodes:
        lines.append(f"二次影響ノード: {', '.join(incident.secondary_nodes)}")
    lines.append(f"関連ログ ({incident.raw_log_count} 件 — 最新 10 件):")
    for log in incident.raw_logs[:10]:
        lines.append(f"  {log}")
    return "\n".join(lines)


class InvestigationAgent:
    def __init__(self, dispatcher: ToolDispatcher, llm_client) -> None:
        self._dispatcher = dispatcher
        self._llm = llm_client

    async def investigate(self, incident: Incident) -> InvestigationReport:
        """エージェントループを実行して InvestigationReport を返す。"""
        started_at = datetime.now(tz=timezone.utc)
        report = InvestigationReport(
            incident_id=incident.incident_id,
            started_at=started_at,
            status="running",
        )

        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"以下のインシデントを調査してください:\n\n{_incident_context(incident)}",
            },
        ]

        try:
            for turn in range(_MAX_TURNS):
                _logger.info(
                    "Investigation turn %d/%d  incident=%s",
                    turn + 1, _MAX_TURNS, incident.incident_id,
                )

                response = await asyncio.to_thread(
                    self._llm.chat_with_tools, messages, TOOL_DEFINITIONS
                )

                finish_reason = response.get("finish_reason")

                if finish_reason == "stop":
                    report.summary = response.get("content") or ""
                    break

                if finish_reason == "tool_calls":
                    tool_calls = response["tool_calls"] or []
                    # アシスタントのターンをメッセージ履歴に追加
                    messages.append({
                        "role": "assistant",
                        "content": response.get("content"),
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": tc["function"],
                            }
                            for tc in tool_calls
                        ],
                    })
                    # ツールを実行してメッセージ履歴に追加
                    for tc in tool_calls:
                        tool_name = tc["function"]["name"]
                        try:
                            args = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
                            args = {}
                        _logger.info("Tool call: %s(%s)", tool_name, args)
                        try:
                            result = await self._dispatcher.dispatch(tool_name, args)
                        except Exception as exc:
                            result = f"ERROR: {exc}"
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })
                else:
                    report.summary = response.get("content") or ""
                    break

            else:
                _logger.warning(
                    "最大ターン数 (%d) に到達しました: incident=%s", _MAX_TURNS, incident.incident_id
                )
                # 最後のアシスタントメッセージを要約として使用
                for msg in reversed(messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        report.summary = msg["content"]
                        break

            report.status = "completed"

        except Exception as exc:
            _logger.exception("調査エラー: incident=%s", incident.incident_id)
            report.status = "failed"
            report.error = str(exc)

        report.completed_at = datetime.now(tz=timezone.utc)
        return report
