"""スライディングウィンドウバッファ。

window_sec 秒後に蓄積メッセージを on_flush コールバックへ渡す。
max_size を超えた場合は最古のメッセージを自動破棄 (リングバッファ)。
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Callable

from topology_syslog.models import SyslogMessage


class TimeWindowBuffer:
    def __init__(
        self,
        window_sec: int,
        max_size: int,
        on_flush: Callable[[list[SyslogMessage]], None],
    ) -> None:
        if not (10 <= window_sec <= 600):
            raise ValueError(f"window_sec は 10〜600 の範囲で指定してください (got {window_sec})")
        self._window_sec = window_sec
        self._max_size = max_size
        self._on_flush = on_flush
        self._buffer: deque[SyslogMessage] = deque(maxlen=max_size)
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def add(self, msg: SyslogMessage) -> None:
        with self._lock:
            self._buffer.append(msg)
            if self._timer is None:
                self._timer = threading.Timer(self._window_sec, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def flush_now(self) -> None:
        """テスト・シャットダウン用の即時フラッシュ。"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            msgs = list(self._buffer)
            self._buffer.clear()
        if msgs:
            self._on_flush(msgs)

    def _flush(self) -> None:
        with self._lock:
            self._timer = None
            msgs = list(self._buffer)
            self._buffer.clear()
        if msgs:
            self._on_flush(msgs)
