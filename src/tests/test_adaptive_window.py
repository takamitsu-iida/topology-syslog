"""アダプティブタイムウィンドウ — バースト検出ロジックのユニットテスト。"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from topology_syslog.api.main import _burst_detected


def _msg(offset_secs: float) -> MagicMock:
    m = MagicMock()
    m.received_at = datetime.now(tz=timezone.utc) - timedelta(seconds=offset_secs)
    return m


def test_burst_detected_when_threshold_met():
    """直近ウィンドウ内のメッセージ数が閾値以上 → バースト検出"""
    # 0〜2.5秒前に 5 件（バースト判定ウィンドウ 5 秒）
    buffer = [_msg(i * 0.5) for i in range(5)]
    assert _burst_detected(buffer, burst_window_sec=5.0, burst_threshold=5) is True


def test_burst_not_detected_below_threshold():
    """メッセージ数が閾値未満 → バースト非検出"""
    buffer = [_msg(i * 0.5) for i in range(4)]
    assert _burst_detected(buffer, burst_window_sec=5.0, burst_threshold=5) is False


def test_burst_not_detected_when_messages_outside_window():
    """メッセージが全てウィンドウ外（古い）→ バースト非検出"""
    buffer = [_msg(10.0 + i) for i in range(10)]  # 全て 10 秒以上前
    assert _burst_detected(buffer, burst_window_sec=5.0, burst_threshold=5) is False


def test_burst_detection_disabled_when_threshold_zero():
    """`burst_threshold=0` のとき常に False"""
    buffer = [_msg(0.1) for _ in range(100)]
    assert _burst_detected(buffer, burst_window_sec=5.0, burst_threshold=0) is False


def test_burst_detection_disabled_when_window_zero():
    """`burst_window_sec=0` のとき常に False"""
    buffer = [_msg(0.1) for _ in range(100)]
    assert _burst_detected(buffer, burst_window_sec=0.0, burst_threshold=5) is False


def test_burst_counts_only_recent_messages():
    """ウィンドウ内外の混在: ウィンドウ内のみがカウントされる"""
    recent = [_msg(1.0) for _ in range(4)]   # 4 件がウィンドウ内
    old    = [_msg(10.0) for _ in range(10)] # 10 件がウィンドウ外
    buffer = recent + old
    # recent 4 件 < threshold 5 → 非検出
    assert _burst_detected(buffer, burst_window_sec=5.0, burst_threshold=5) is False
    # recent 4 件 ≥ threshold 4 → 検出
    assert _burst_detected(buffer, burst_window_sec=5.0, burst_threshold=4) is True
