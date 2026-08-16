from datetime import datetime, timezone

import pytest

from topology_syslog.correlation.time_window_buffer import TimeWindowBuffer
from topology_syslog.models import SyslogMessage


def _msg(hostname: str = "router") -> SyslogMessage:
    return SyslogMessage(
        received_at=datetime.now(tz=timezone.utc),
        source_ip="10.0.0.1",
        hostname=hostname,
        facility=3,
        severity=3,
        message="test",
    )


def test_flush_now_delivers_messages():
    received: list[SyslogMessage] = []
    buf = TimeWindowBuffer(window_sec=10, max_size=100, on_flush=received.extend)
    buf.add(_msg("r1"))
    buf.add(_msg("r2"))
    buf.flush_now()
    assert len(received) == 2


def test_empty_buffer_does_not_invoke_callback():
    called = []
    buf = TimeWindowBuffer(window_sec=10, max_size=100, on_flush=lambda msgs: called.append(msgs))
    buf.flush_now()
    assert called == []


def test_ring_buffer_drops_oldest():
    received: list[SyslogMessage] = []
    buf = TimeWindowBuffer(window_sec=10, max_size=3, on_flush=received.extend)
    for i in range(5):
        buf.add(_msg(f"host-{i}"))
    buf.flush_now()
    # maxlen=3 なので最新の3件のみ保持される
    assert len(received) == 3
    assert {m.hostname for m in received} == {"host-2", "host-3", "host-4"}


def test_invalid_window_sec_raises():
    with pytest.raises(ValueError):
        TimeWindowBuffer(window_sec=9, max_size=100, on_flush=lambda x: None)
    with pytest.raises(ValueError):
        TimeWindowBuffer(window_sec=601, max_size=100, on_flush=lambda x: None)


def test_boundary_window_sec_valid():
    # 境界値 10 と 600 は有効
    TimeWindowBuffer(window_sec=10,  max_size=100, on_flush=lambda x: None)
    TimeWindowBuffer(window_sec=600, max_size=100, on_flush=lambda x: None)


def test_double_flush_does_not_duplicate():
    received: list[SyslogMessage] = []
    buf = TimeWindowBuffer(window_sec=10, max_size=100, on_flush=received.extend)
    buf.add(_msg())
    buf.flush_now()
    buf.flush_now()  # 2回目は空なのでコールバック呼ばれない
    assert len(received) == 1
