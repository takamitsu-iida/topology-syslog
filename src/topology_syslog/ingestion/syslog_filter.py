"""受信 SyslogMessage を無視パターンで除外するフィルター。

パターンはメッセージ文字列への部分一致で判定する。
"""
from __future__ import annotations

from topology_syslog.models import SyslogMessage

# 無設定でも除外するデフォルトパターン
DEFAULT_PATTERNS: list[str] = ["%LINK-2-INTVULN"]


class SyslogFilter:
    def __init__(
        self,
        patterns: list[str] = (),
        *,
        include_defaults: bool = True,
    ) -> None:
        base = list(DEFAULT_PATTERNS) if include_defaults else []
        self._patterns: list[str] = base + [p for p in patterns if p]

    @classmethod
    def from_file(cls, path: str, *, include_defaults: bool = True) -> "SyslogFilter":
        """テキストファイルからパターンを読み込んでインスタンスを生成する。

        # で始まる行と空行はスキップする。
        """
        return cls(_load_patterns(path), include_defaults=include_defaults)

    def is_ignored(self, msg: SyslogMessage) -> bool:
        return any(p in msg.message for p in self._patterns)

    @property
    def patterns(self) -> list[str]:
        return list(self._patterns)


def _load_patterns(path: str) -> list[str]:
    patterns: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
    return patterns
