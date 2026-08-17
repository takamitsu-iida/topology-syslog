"""AI レポート生成 (query_cache / report_generator) のユニットテスト。

chromadb / openai のインストールは不要。RAGStore はモック化する。
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from topology_syslog.ai.query_cache import QueryCache, make_fingerprint
from topology_syslog.ai.report_generator import ReportGenerator
from topology_syslog.models import Incident


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _inc(suffix: str = "01", event: str = "%LINK-3-UPDOWN: Gi0/0 down") -> Incident:
    return Incident(
        incident_id=f"INC-TEST-{suffix}",
        created_at=datetime.now(tz=timezone.utc),
        root_cause_node="Spine1",
        primary_event=event,
        secondary_nodes=["Leaf1", "Leaf2"],
        raw_log_count=3,
        raw_logs=[event],
        status="OPEN",
    )


def _mock_rag() -> MagicMock:
    rag = MagicMock()
    rag.search_similar.return_value = []
    return rag


# ---------------------------------------------------------------------------
# make_fingerprint
# ---------------------------------------------------------------------------

def test_fingerprint_same_event_type_different_detail():
    """同じ %FAC-SEV-MNEM なら詳細が異なってもフィンガープリントが一致する"""
    fp1 = make_fingerprint("Spine1", "%LINK-3-UPDOWN: Gi0/0 down", ["Leaf1"])
    fp2 = make_fingerprint("Spine1", "%LINK-3-UPDOWN: Gi0/1 down", ["Leaf1"])
    assert fp1 == fp2


def test_fingerprint_different_event_type():
    """異なる %FAC-SEV-MNEM はフィンガープリントが異なる"""
    fp1 = make_fingerprint("Spine1", "%LINK-3-UPDOWN: down",          ["Leaf1"])
    fp2 = make_fingerprint("Spine1", "%BGP-5-ADJCHANGE: neighbor down", ["Leaf1"])
    assert fp1 != fp2


def test_fingerprint_different_secondary_nodes():
    """secondary_nodes が異なればフィンガープリントが異なる"""
    fp1 = make_fingerprint("Spine1", "%LINK-3-UPDOWN: down", ["Leaf1"])
    fp2 = make_fingerprint("Spine1", "%LINK-3-UPDOWN: down", ["Leaf1", "Leaf2"])
    assert fp1 != fp2


def test_fingerprint_no_cisco_event():
    """Cisco イベント種別がなくても動作する（空文字列でキー生成）"""
    fp = make_fingerprint("Router1", "arbitrary log message", [])
    assert isinstance(fp, str) and len(fp) == 64


# ---------------------------------------------------------------------------
# QueryCache
# ---------------------------------------------------------------------------

def test_cache_miss_returns_none():
    cache = QueryCache("sqlite:///:memory:")
    result = cache.get("Spine1", "%LINK-3-UPDOWN: down", ["Leaf1"])
    assert result is None


def test_cache_set_and_get():
    cache = QueryCache("sqlite:///:memory:")
    cache.set("Spine1", "%LINK-3-UPDOWN: down", ["Leaf1"], "test report")
    result = cache.get("Spine1", "%LINK-3-UPDOWN: down", ["Leaf1"])
    assert result == "test report"


def test_cache_hit_normalized_event():
    """詳細が違っても同じ %FAC-SEV-MNEM ならキャッシュがヒットする"""
    cache = QueryCache("sqlite:///:memory:")
    cache.set("Spine1", "%LINK-3-UPDOWN: Gi0/0 down", ["Leaf1"], "cached")
    result = cache.get("Spine1", "%LINK-3-UPDOWN: Gi0/1 down", ["Leaf1"])
    assert result == "cached"


# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------

def test_cache_miss_calls_llm_and_caches():
    """キャッシュミス時に LLM が呼ばれ、結果がキャッシュされる"""
    llm = MagicMock()
    llm.ask.return_value = "generated report"
    rag = _mock_rag()
    cache = QueryCache("sqlite:///:memory:")

    gen = ReportGenerator(llm, cache, rag)
    inc = _inc()
    report = gen.generate(inc)

    assert report == "generated report"
    llm.ask.assert_called_once()
    rag.add.assert_called_once_with(inc)
    # キャッシュに保存されたことを確認
    assert cache.get(inc.root_cause_node, inc.primary_event, inc.secondary_nodes) == "generated report"


def test_cache_hit_skips_llm():
    """キャッシュヒット時に LLM を呼ばない"""
    llm = MagicMock()
    rag = _mock_rag()
    cache = QueryCache("sqlite:///:memory:")

    inc = _inc()
    cache.set(inc.root_cause_node, inc.primary_event, inc.secondary_nodes, "cached report")

    gen = ReportGenerator(llm, cache, rag)
    report = gen.generate(inc)

    assert report == "cached report"
    llm.ask.assert_not_called()
    rag.add.assert_not_called()


def test_similar_incidents_included_in_prompt():
    """RAG が類似事例を返したとき、プロンプトに含まれる"""
    llm = MagicMock()
    llm.ask.return_value = "report with context"
    rag = _mock_rag()
    rag.search_similar.return_value = ["過去インシデント1の内容", "過去インシデント2の内容"]

    cache = QueryCache("sqlite:///:memory:")
    gen = ReportGenerator(llm, cache, rag)
    gen.generate(_inc())

    prompt_arg = llm.ask.call_args[0][0]
    assert "過去インシデント1の内容" in prompt_arg
    assert "過去インシデント2の内容" in prompt_arg


def test_no_similar_incidents_no_similar_section():
    """RAG が空のとき、プロンプトに類似セクションが含まれない"""
    llm = MagicMock()
    llm.ask.return_value = "report"
    cache = QueryCache("sqlite:///:memory:")
    gen = ReportGenerator(llm, cache, _mock_rag())
    gen.generate(_inc())

    prompt_arg = llm.ask.call_args[0][0]
    assert "過去の類似インシデント" not in prompt_arg
