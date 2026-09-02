"""復旧 SYSLOG を既存インシデントへ対応付けるマッチャー。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from topology_syslog.models import Incident, SyslogMessage


class RecoveryMatchScope(StrEnum):
    ROOT = "root"
    SECONDARY = "secondary"
    INTERFACE = "interface"
    PEER = "peer"


@dataclass(frozen=True)
class RecoveryMatch:
    incident: Incident
    scope: RecoveryMatchScope
    matched_node: str
    evidence: str
    matched_interface: str | None = None
    matched_peer: str | None = None


_INTERFACE_RE = re.compile(
    r"\b(?:Interface|interface|Line protocol on Interface)\s+([A-Za-z][A-Za-z0-9./_-]+)",
    re.IGNORECASE,
)
_PEER_RE = re.compile(r"\bneighbor\s+([A-Za-z0-9_.:-]+)", re.IGNORECASE)


class RecoveryMatcher:
    def find_matches(
        self,
        recovery: SyslogMessage,
        open_incidents: list[Incident],
    ) -> list[RecoveryMatch]:
        if not recovery.is_recovery:
            return []

        matches: list[RecoveryMatch] = []
        recovery_interface = extract_interface(recovery.message)
        recovery_peer = extract_peer(recovery.message)

        for incident in open_incidents:
            if incident.status != "OPEN":
                continue
            if recovery.hostname == incident.root_cause_node:
                matches.append(RecoveryMatch(
                    incident=incident,
                    scope=RecoveryMatchScope.ROOT,
                    matched_node=recovery.hostname,
                    evidence=recovery.message,
                ))
            elif recovery.hostname in incident.secondary_nodes:
                matches.append(RecoveryMatch(
                    incident=incident,
                    scope=RecoveryMatchScope.SECONDARY,
                    matched_node=recovery.hostname,
                    evidence=recovery.message,
                ))

            incident_text = "\n".join([incident.primary_event, *incident.raw_logs, *incident.recovery_evidence])
            if recovery_interface and recovery_interface in incident_text:
                matches.append(RecoveryMatch(
                    incident=incident,
                    scope=RecoveryMatchScope.INTERFACE,
                    matched_node=recovery.hostname,
                    matched_interface=recovery_interface,
                    evidence=recovery.message,
                ))
            if recovery_peer and recovery_peer in incident_text:
                matches.append(RecoveryMatch(
                    incident=incident,
                    scope=RecoveryMatchScope.PEER,
                    matched_node=recovery.hostname,
                    matched_peer=recovery_peer,
                    evidence=recovery.message,
                ))

        return _dedupe(matches)


def extract_interface(message: str) -> str | None:
    match = _INTERFACE_RE.search(message)
    return match.group(1).rstrip(",:") if match else None


def extract_peer(message: str) -> str | None:
    match = _PEER_RE.search(message)
    return match.group(1).rstrip(",:") if match else None


def _dedupe(matches: list[RecoveryMatch]) -> list[RecoveryMatch]:
    seen: set[tuple[str, RecoveryMatchScope, str | None, str | None, str]] = set()
    deduped: list[RecoveryMatch] = []
    for match in matches:
        key = (
            match.incident.incident_id,
            match.scope,
            match.matched_interface,
            match.matched_peer,
            match.matched_node,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
    return deduped