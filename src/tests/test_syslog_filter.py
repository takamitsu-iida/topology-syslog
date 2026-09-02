"""SyslogFilter のテスト。"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from topology_syslog.ingestion.syslog_filter import DEFAULT_PATTERNS, SyslogFilter
from topology_syslog.models import SyslogMessage

_IGNORE_FILE = str(
    Path(__file__).parent.parent.parent / "configs" / "syslog_ignore.txt"
)


def _msg(message: str) -> SyslogMessage:
    return SyslogMessage(
        received_at=datetime.now(tz=timezone.utc),
        source_ip="10.0.0.1",
        hostname="router1",
        facility=3,
        severity=3,
        message=message,
    )


# ---- デフォルトパターン ---------------------------------------------------

def test_default_filter_does_not_ignore_legacy_pattern():
    f = SyslogFilter()
    assert not f.is_ignored(_msg("Interface: %LINK-2-INTVULN: Gi0/0"))


def test_default_pattern_not_in_list_when_disabled():
    f = SyslogFilter(include_defaults=False)
    assert not f.is_ignored(_msg("%LINK-2-INTVULN"))


# ---- カスタムパターン ---------------------------------------------------

def test_custom_pattern_ignored():
    f = SyslogFilter(["%SYS-5-CONFIG_I"])
    assert f.is_ignored(_msg("Configured from console by %SYS-5-CONFIG_I"))


def test_non_matching_not_ignored():
    f = SyslogFilter(["%SYS-5-CONFIG_I"])
    assert not f.is_ignored(_msg("%LINK-3-UPDOWN: Interface GE0/0 down"))


def test_empty_filter_only_defaults():
    f = SyslogFilter()
    assert f.patterns == DEFAULT_PATTERNS


# ---- ファイル読み込み ---------------------------------------------------

def test_from_file_loads_migrated_file_without_patterns():
    f = SyslogFilter.from_file(_IGNORE_FILE)
    assert f.patterns == []


def test_from_file_skips_comments_and_blank_lines():
    f = SyslogFilter.from_file(_IGNORE_FILE, include_defaults=False)
    # コメント行・空行はパターンに含まれない
    for p in f.patterns:
        assert not p.startswith("#")
        assert p.strip() != ""


# ---- API 経由のフィルター統合テスト ---------------------------------------

def test_ingest_filters_ignored_messages(client, app):
    """POST /ingest で無視パターンに一致するメッセージがインシデントを生成しない。"""
    # app.state.syslog_filter にカスタムパターンを上書き
    app.state.syslog_filter = SyslogFilter(
        ["%SYS-5-CONFIG_I", "%SYS-5-LOG_CONFIG_CHANGE"],
        include_defaults=False,
    )
    resp = client.post("/ingest", json={"messages": [
        {"source_ip": "10.0.0.1",
         "raw": "<34>Aug 16 10:00:00 Core-Router1 %SYS-5-CONFIG_I: Configured"},
        {"source_ip": "10.0.0.2",
         "raw": "<34>Aug 16 10:00:01 Spine1 %SYS-5-LOG_CONFIG_CHANGE: log changed"},
    ]})
    assert resp.status_code == 200
    assert resp.json() == []


def test_ingest_passes_non_ignored_messages(client):
    """無視パターンに一致しないメッセージは通常どおり処理される。"""
    resp = client.post("/ingest", json={"messages": [
        {"source_ip": "192.168.1.1",
         "raw": "<34>Aug 16 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface GE0/0 down"},
    ]})
    assert resp.status_code == 200
    # トポロジーに存在するホストなのでインシデントが生成される
    assert len(resp.json()) >= 1
