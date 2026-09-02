"""SYSLOG メッセージからベンダーと安定した照合シグネチャを生成する。"""
from __future__ import annotations

import re

_CISCO_EVENT_RE = re.compile(r"%([A-Z0-9_]+)-[0-7]-([A-Z0-9_]+)")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_NUMBER_RE = re.compile(r"\b\d+\b")
_WHITESPACE_RE = re.compile(r"\s+")

_VENDOR_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("juniper-junos", ("RPD_", "SNMP_TRAP_LINK_", "UI_COMMIT", "CHASSISD_", "LACP_", "BGP_")),
    ("arista-eos", ("%BGP-", "%LINEPROTO-", "%LACP-", "%STP-", "%SYS-")),
    ("paloalto-panos", ("PAN-OS", "PALO ALTO", "SYSTEM,", "THREAT,", "CONFIG,", "HA,")),
    ("fortinet-fortios", ("FGT", "FORTIGATE", "LOG_ID=", "SUBTYPE=", "MSG=", "HA FAILOVER")),
    ("yamaha-rtx", ("YAMAHA", "RTX", "PP[", "IPSEC", "TUNNEL", "BGP")),
    ("nec-ix", ("NEC", "IX", "WEB-GUI", "IF-", "BGP-")),
    ("allied-telesis-awplus", ("AWPLUS", "ALLIED", "INTERFACE", "EPSR", "LACP", "STP")),
)


def normalize(event_type: str | None, message: str) -> tuple[str | None, str]:
    """(vendor, signature) を返す。Cisco イベントは Severity をワイルドカード化する。"""
    match = _CISCO_EVENT_RE.search(event_type or message)
    if match:
        return "cisco-ios", f"%{match.group(1)}-*-{match.group(2)}"

    normalized = _IP_RE.sub("<ip>", message.upper())
    normalized = _NUMBER_RE.sub("<n>", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return _detect_vendor(normalized), normalized or "<empty>"


def _detect_vendor(normalized_message: str) -> str | None:
    for vendor, hints in _VENDOR_HINTS:
        if any(hint in normalized_message for hint in hints):
            return vendor
    return None