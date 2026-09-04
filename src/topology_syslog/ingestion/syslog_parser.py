"""RFC 3164 / RFC 5424 syslog パーサー。"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from topology_syslog.knowledge.normalizer import normalize
from topology_syslog.models import SyslogMessage

# Cisco IOS 形式 (%FACILITY-SEV-MNEMONIC)
_CISCO_RE = re.compile(r"%[A-Z0-9_]+-\d+-[A-Z0-9_]+")

# 復旧イベントパターン: リンクアップ / BGP Up / OSPF FULL など
_RECOVERY_RE = re.compile(
    r'changed\s+state\s+to\s+up\b'       # LINK / LINEPROTO up
    r'|ADJCHANGE[^\n]*\bUp\b'             # BGP neighbor Up
    r'|ADJCHG[^\n]*\bto\s+FULL\b'        # OSPF neighbor FULL
    r'|ADJCHANGE[^\n]*\bUP\b'             # ISIS / generic adjacency UP
    r'|%SYS-\d+-RESTART',                 # システム再起動
    re.IGNORECASE,
)

# Cisco "logging origin-id hostname" が付与するプレフィックス: "<seq>: <hostname>: "
_CISCO_ORIGIN_RE = re.compile(r"^\d+:\s+(\S+?):\s+")

# IPアドレス判定
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

# RFC 3164 タイムスタンプ: "Aug  1 10:00:00" または "Aug 15 10:00:00"
_RFC3164_TS_RE = re.compile(
    r"^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)?$",
    re.DOTALL,
)

# Aruba Instant AP: "2026-09-04T06:26:12+09:00 2026 192.0.2.1 cli[123]: <541004> <WARN> AP:name <ip mac> message"
_ARUBA_IAP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})\s+"
    r"\d{4}\s+"
    r"(?P<host_ip>\S+)\s+"
    r"(?P<process>\S+):\s+"
    r"<(?P<event_code>\d+)>\s+"
    r"<(?P<level>[A-Z]+)>\s+"
    r"AP:(?P<ap_name>\S+)\s+"
    r"<(?P<ap_identity>[^>]+)>\s+"
    r"(?P<message>.*)$",
    re.DOTALL,
)

_ARUBA_SEVERITY = {
    "EMERG": 0,
    "EMERGENCY": 0,
    "ALERT": 1,
    "CRIT": 2,
    "CRITICAL": 2,
    "ERR": 3,
    "ERROR": 3,
    "WARN": 4,
    "WARNING": 4,
    "NOTICE": 5,
    "INFO": 6,
    "INFORMATIONAL": 6,
    "DEBUG": 7,
}


def parse(raw: bytes, source_ip: str) -> SyslogMessage:
    text = raw.decode("utf-8", errors="replace").strip()
    now = datetime.now(tz=timezone.utc)

    msg = (
        _try_rfc5424(text, source_ip, now)
        or _try_rfc3164(text, source_ip, now)
        or _try_aruba_iap(text, source_ip, now)
        or _fallback(text, source_ip, now)
    )
    msg.is_recovery = bool(_RECOVERY_RE.search(msg.message))
    msg.vendor, msg.normalized_signature = normalize(msg.event_type, msg.message)
    return msg


def _extract_pri(text: str) -> tuple[int, str] | None:
    """<PRI> プレフィックスを解析して (pri_int, rest) を返す。失敗時は None。"""
    if not text.startswith("<"):
        return None
    end = text.find(">")
    if end < 2:
        return None
    try:
        return int(text[1:end]), text[end + 1:]
    except ValueError:
        return None


def _try_rfc5424(text: str, source_ip: str, now: datetime) -> SyslogMessage | None:
    result = _extract_pri(text)
    if result is None:
        return None
    pri, rest = result
    # RFC 5424 では PRI の直後が VERSION (単一数字)
    parts = rest.split(None, 7)
    if len(parts) < 6 or not parts[0].isdigit():
        return None
    hostname = parts[2] if parts[2] != "-" else source_ip
    message = parts[7].strip() if len(parts) > 7 else ""
    if _IP_RE.match(hostname):
        origin = _CISCO_ORIGIN_RE.match(message)
        if origin:
            hostname = origin.group(1)
    facility, severity = pri >> 3, pri & 7
    return SyslogMessage(
        received_at=now,
        source_ip=source_ip,
        hostname=hostname,
        facility=facility,
        severity=severity,
        message=message,
        event_type=_cisco_event(message),
    )


def _try_rfc3164(text: str, source_ip: str, now: datetime) -> SyslogMessage | None:
    result = _extract_pri(text)
    if result is None:
        return None
    pri, rest = result
    m = _RFC3164_TS_RE.match(rest)
    if not m:
        return None
    hostname = m.group(2)
    message = (m.group(3) or "").strip()
    # hostnameがIPアドレスの場合、メッセージ中の "<seq>: <name>: " からノード名を抽出する
    if _IP_RE.match(hostname):
        origin = _CISCO_ORIGIN_RE.match(message)
        if origin:
            hostname = origin.group(1)
    facility, severity = pri >> 3, pri & 7
    return SyslogMessage(
        received_at=now,
        source_ip=source_ip,
        hostname=hostname,
        facility=facility,
        severity=severity,
        message=message,
        event_type=_cisco_event(message),
    )


def _try_aruba_iap(text: str, source_ip: str, now: datetime) -> SyslogMessage | None:
    m = _ARUBA_IAP_RE.match(text)
    if not m:
        return None
    level = m.group("level")
    return SyslogMessage(
        received_at=now,
        source_ip=source_ip,
        hostname=m.group("ap_name"),
        facility=1,
        severity=_ARUBA_SEVERITY.get(level, 5),
        message=m.group("message").strip(),
        event_type=f"ARUBA-{m.group('event_code')}",
    )


def _fallback(text: str, source_ip: str, now: datetime) -> SyslogMessage:
    return SyslogMessage(
        received_at=now,
        source_ip=source_ip,
        hostname=source_ip,
        facility=1,
        severity=5,
        message=text,
        event_type=_cisco_event(text),
    )


def _cisco_event(message: str) -> str | None:
    m = _CISCO_RE.search(message)
    return m.group() if m else None
