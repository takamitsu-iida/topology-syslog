"""SYSLOG to causal Observation normalization for hypothesis-based RCA."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from topology_syslog.knowledge.store import KnowledgeRule
from topology_syslog.models import EventAction, EventClassification, SyslogMessage
from topology_syslog.topology.causal_topology import CausalTopology, device_object_id, interface_object_id, normalize_interface_id

_INTERFACE_RE = re.compile(r"\bInterface\s+([^,\s]+)", re.IGNORECASE)
_INTERFACE_STATE_RE = re.compile(r"\bInterface\s+([^,\s]+).*\b(?:down|up|administratively down)\b", re.IGNORECASE)
_BGP_NEIGHBOR_RE = re.compile(
    r"\bneighbor\s+(\S+).*\b(?:down|up|reset|hold time expired|removed from session)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    source_node: str
    observed_object: str
    assertion: str
    signature: str | None
    severity: int
    raw_message: str
    confidence: float = 1.0
    received_at: datetime | None = None
    classification: str = EventClassification.UNKNOWN.value
    action: str | None = None
    knowledge_id: str | None = None
    peer_device: str | None = None


class ObservationNormalizer:
    def __init__(self, topology: CausalTopology) -> None:
        self._topology = topology

    def normalize(self, message: SyslogMessage, rule: KnowledgeRule | None = None) -> Observation | None:
        if message.hostname not in self._topology.devices:
            return None

        observed_object, object_confidence, peer_device = self._observed_object(message)
        assertion = _assertion_for(message)
        confidence = _confidence_for(message, rule, object_confidence, assertion)
        return Observation(
            observed_at=message.received_at,
            source_node=message.hostname,
            observed_object=observed_object,
            assertion=assertion,
            signature=message.normalized_signature or message.event_type,
            severity=message.severity,
            raw_message=message.message,
            confidence=confidence,
            received_at=message.received_at,
            classification=message.event_classification.value,
            action=message.event_action.value if message.event_action is not None else None,
            knowledge_id=message.knowledge_id or (rule.rule_id if rule is not None else None),
            peer_device=peer_device,
        )

    def _observed_object(self, message: SyslogMessage) -> tuple[str, float, str | None]:
        if match := _INTERFACE_STATE_RE.search(message.message):
            interface_id = self._resolve_interface_id(message.hostname, match.group(1))
            return (
                self._topology.interface_object(message.hostname, interface_id)
                or interface_object_id(message.hostname, interface_id),
                0.95,
                None,
            )

        if _is_bgp_event(message) and (match := _BGP_NEIGHBOR_RE.search(message.message)):
            peer = self._resolve_peer(match.group(1))
            if peer is not None:
                session = self._topology.bgp_session_for_devices(message.hostname, peer)
                if session is not None:
                    return session, 0.9, peer
            return device_object_id(message.hostname), 0.45, peer

        if match := _INTERFACE_RE.search(message.message):
            interface_id = self._resolve_interface_id(message.hostname, match.group(1))
            interface_object = self._topology.interface_object(message.hostname, interface_id)
            if interface_object is not None:
                return interface_object, 0.65, None

        return device_object_id(message.hostname), 0.5, None

    def _resolve_peer(self, token: str) -> str | None:
        normalized = token.strip().rstrip(",.;)")
        if normalized in self._topology.devices:
            return normalized
        return self._topology.resolve_device_by_address(normalized)

    def _resolve_interface_id(self, device_id: str, interface_id: str) -> str:
        if self._topology.interface_object(device_id, interface_id) is not None:
            return interface_id
        shortened = normalize_interface_id(interface_id)
        if self._topology.interface_object(device_id, shortened) is not None:
            return shortened
        return interface_id


def _is_bgp_event(message: SyslogMessage) -> bool:
    signature = message.normalized_signature or message.event_type or ""
    return "%BGP" in signature.upper() or "%BGP" in message.message.upper()


def _assertion_for(message: SyslogMessage) -> str:
    classification = message.event_classification
    action = message.event_action
    if message.is_recovery or classification == EventClassification.RECOVERY:
        return "recovery"
    if action == EventAction.RETAIN_ONLY or classification in {EventClassification.NOISE, EventClassification.RETAIN_ONLY}:
        return "noise"
    if classification == EventClassification.FAULT_SIGNAL or action == EventAction.CREATE_INCIDENT:
        return "fault"
    if classification in {EventClassification.STATE_CHANGE, EventClassification.CONFIG_CHANGE} or action == EventAction.CORRELATE_ONLY:
        return "state_change"
    if classification == EventClassification.SECURITY:
        return "security"
    return "fault"


def _confidence_for(
    message: SyslogMessage,
    rule: KnowledgeRule | None,
    object_confidence: float,
    assertion: str,
) -> float:
    classification = message.event_classification
    if assertion == "noise":
        base = min(object_confidence, 0.2)
    elif classification == EventClassification.UNKNOWN and rule is None:
        base = min(object_confidence, 0.35)
    elif assertion == "recovery":
        base = max(object_confidence, 0.8)
    else:
        base = object_confidence
    if rule is not None and rule.confidence is not None:
        base = min(base, rule.confidence)
    return round(max(0.0, min(1.0, base)), 3)