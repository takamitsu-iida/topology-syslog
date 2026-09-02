"""インシデント AI レポート生成器 — RAG コンテキスト + LLM + クエリキャッシュ。"""
from __future__ import annotations

import logging

from topology_syslog.ai.llm_client import LLMClient
from topology_syslog.ai.query_cache import QueryCache
from topology_syslog.ai.rag_store import RAGStore
from topology_syslog.models import Incident

_logger = logging.getLogger(__name__)

_PROMPT = """\
あなたはネットワーク障害解析の専門家AIです。
以下の情報を元に、日本語でインシデントレポートを作成してください。

## 現在のインシデント
{incident_summary}
{similar_section}
## レポート形式（必ず以下の項目を含めること）
1. **障害概要** — 何が起きたか 1〜2 行で
2. **根本原因の分析** — 最も可能性の高い原因と根拠
3. **影響範囲** — 影響ノードと想定される業務影響
4. **推奨対応** — 即時対応 / 恒久対応の具体的手順
5. **予防策** — 再発防止のための提言
"""

_SIMILAR_TMPL = """\

## 過去の類似インシデント（参考）
{cases}

"""


def _summarize(incident: Incident) -> str:
    lines = [
        f"- インシデントID: {incident.incident_id}",
        f"- 根本原因ノード: {incident.root_cause_node}",
        f"- 主要イベント: {incident.primary_event}",
    ]
    if incident.secondary_nodes:
        lines.append(f"- 二次影響ノード: {', '.join(incident.secondary_nodes)}")
    lines.append(f"- 関連ログ数: {incident.raw_log_count}")
    for log in incident.raw_logs[:10]:
        lines.append(f"  - {log}")
    if incident.rca_explanation.primary_candidate is not None:
        rca = incident.rca_explanation
        primary = rca.primary_candidate
        lines.append("")
        lines.append("## RCA 判定コンテキスト")
        lines.append(f"- RCA confidence: {_format_confidence(rca.confidence)}")
        lines.append(f"- 採用候補: {primary.node_id} ({_format_confidence(primary.confidence)})")
        if primary.evidences:
            lines.append("- 判断根拠:")
            for evidence in primary.evidences:
                lines.append(f"  - [{evidence.source}] +{_format_confidence(evidence.weight)} {evidence.summary}")
                if evidence.related_nodes:
                    lines.append(f"    - 関連ノード: {', '.join(evidence.related_nodes)}")
        if rca.alternative_candidates:
            lines.append("- 代替候補:")
            for candidate in rca.alternative_candidates[:5]:
                reason = f" / {candidate.alternative_reason}" if candidate.alternative_reason else ""
                lines.append(f"  - {candidate.node_id}: {_format_confidence(candidate.confidence)}{reason}")
    return "\n".join(lines)


def _format_confidence(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{round(value * 100)}%"


class ReportGenerator:
    def __init__(self, llm: LLMClient, cache: QueryCache, rag: RAGStore) -> None:
        self._llm   = llm
        self._cache = cache
        self._rag   = rag

    def generate(self, incident: Incident) -> str:
        """レポートを返す。キャッシュヒット時は LLM を呼び出さない。"""
        cached = self._cache.get(
            incident.root_cause_node,
            incident.primary_event,
            incident.secondary_nodes,
        )
        if cached:
            _logger.debug("Cache hit for %s", incident.incident_id)
            return cached

        similar = self._rag.search_similar(incident)
        similar_section = (
            _SIMILAR_TMPL.format(cases="\n---\n".join(similar)) if similar else ""
        )
        prompt = _PROMPT.format(
            incident_summary=_summarize(incident),
            similar_section=similar_section,
        )

        _logger.info("Calling LLM for incident %s", incident.incident_id)
        report = self._llm.ask(prompt)

        self._cache.set(incident.root_cause_node, incident.primary_event, incident.secondary_nodes, report)
        self._rag.add(incident)

        return report

    def purge_cache(self) -> int:
        """TTL 切れのキャッシュ行を削除して削除件数を返す。"""
        return self._cache.purge_expired()
