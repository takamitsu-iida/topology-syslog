"""インシデントの自動状態遷移ルール。"""
from __future__ import annotations

from datetime import datetime

from topology_syslog.correlation.recovery_matcher import RecoveryMatch, RecoveryMatchScope
from topology_syslog.models import Incident, IncidentCondition, SyslogMessage


class IncidentLifecycle:
    def apply_recovery(self, incident: Incident, matches: list[RecoveryMatch], at: datetime) -> Incident:
        relevant = [match for match in matches if match.incident.incident_id == incident.incident_id]
        if not relevant or incident.status != "OPEN":
            return incident

        incident.last_recovery_at = at
        for match in relevant:
            if match.evidence not in incident.recovery_evidence:
                incident.recovery_evidence.append(match.evidence)

        scopes = {match.scope for match in relevant}
        if RecoveryMatchScope.ROOT in scopes:
            incident.condition = IncidentCondition.RECOVERING.value
        else:
            incident.condition = IncidentCondition.DEGRADED.value
        return incident

    def apply_fault(self, incident: Incident, message: SyslogMessage, flap_threshold: int = 2) -> Incident:
        if incident.status != "OPEN":
            return incident

        incident.last_fault_at = message.received_at
        if incident.condition in {IncidentCondition.RECOVERING.value, IncidentCondition.RECOVERED.value}:
            incident.flap_count += 1
            if incident.flap_count >= flap_threshold:
                incident.condition = IncidentCondition.FLAPPING.value
            else:
                incident.condition = IncidentCondition.ACTIVE.value
        elif incident.condition == IncidentCondition.FLAPPING.value:
            incident.flap_count += 1
        else:
            if incident.flap_count > 0:
                incident.flap_count += 1
                if incident.flap_count >= flap_threshold:
                    incident.condition = IncidentCondition.FLAPPING.value
                    return incident
            incident.condition = IncidentCondition.ACTIVE.value
        return incident

    def mark_recovered(self, incident: Incident, at: datetime) -> Incident:
        if incident.status != "OPEN":
            return incident
        incident.condition = IncidentCondition.RECOVERED.value
        incident.last_recovery_at = incident.last_recovery_at or at
        return incident