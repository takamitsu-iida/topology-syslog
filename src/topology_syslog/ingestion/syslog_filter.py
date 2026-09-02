"""受信 SyslogMessage を無視パターンで除外するフィルター。

パターンはメッセージ文字列への部分一致で判定する。
デバイスごとに syslog-min-severity を設定することで、重要度が低いメッセージを装置単位で除外できる。
"""
from __future__ import annotations

from topology_syslog.models import SyslogMessage

# 旧 SYSLOG_IGNORE_FILE の互換用。標準の無視ルールは SKB に移行済み。
DEFAULT_PATTERNS: list[str] = []

# RFC 5424 severity 名 → 数値 (0=Emergency, 7=Debug)
SEVERITY_NAMES: dict[str, int] = {
    "emergency":     0,
    "alert":         1,
    "critical":      2,
    "error":         3,
    "warning":       4,
    "notice":        5,
    "informational": 6,
    "debug":         7,
}

_DEFAULT_SEVERITY = 7  # 未設定時はすべて受け入れる


def parse_severity(value: str | int) -> int:
    """文字列または整数の severity 値を数値に正規化する。"""
    if isinstance(value, int):
        return value
    normalized = value.strip().lower()
    if normalized in SEVERITY_NAMES:
        return SEVERITY_NAMES[normalized]
    try:
        return int(normalized)
    except ValueError:
        raise ValueError(f"Unknown severity level: {value!r}") from None


class SyslogFilter:
    def __init__(
        self,
        patterns: list[str] = (),
        *,
        include_defaults: bool = True,
        device_severity: dict[str, int] | None = None,
        default_severity: int = _DEFAULT_SEVERITY,
    ) -> None:
        base = list(DEFAULT_PATTERNS) if include_defaults else []
        self._patterns: list[str] = base + [p for p in patterns if p]
        self._device_severity: dict[str, int] = dict(device_severity or {})
        self._default_severity: int = default_severity

    @classmethod
    def from_file(cls, path: str, *, include_defaults: bool = True) -> "SyslogFilter":
        """テキストファイルからパターンを読み込んでインスタンスを生成する。

        # で始まる行と空行はスキップする。
        """
        return cls(_load_patterns(path), include_defaults=include_defaults)

    def is_ignored(self, msg: SyslogMessage) -> bool:
        if any(p in msg.message for p in self._patterns):
            return True
        threshold = self._device_severity.get(msg.hostname, self._default_severity)
        # severity 番号が閾値より大きい = より軽微なメッセージ → 除外
        return msg.severity > threshold

    def update_device_severity(self, device_severity: dict[str, int]) -> None:
        """トポロジーリロード時などにデバイス severity マップを更新する。"""
        self._device_severity = dict(device_severity)

    @property
    def patterns(self) -> list[str]:
        return list(self._patterns)

    @property
    def device_severity(self) -> dict[str, int]:
        return dict(self._device_severity)


def _load_patterns(path: str) -> list[str]:
    patterns: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
    return patterns
