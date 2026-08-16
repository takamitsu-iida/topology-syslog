"""汎用 Webhook 通知 (JSON POST)。ITSM 連携などに使用する。"""
from __future__ import annotations

import httpx

from topology_syslog.models import Incident
from topology_syslog.notification.base import BaseNotifier


class WebhookNotifier(BaseNotifier):
    def __init__(
        self,
        url: str,
        *,
        timeout: float = 10.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._headers = headers or {}

    def send(self, incident: Incident) -> None:
        payload = {
            "incident_id":              incident.incident_id,
            "root_cause":               incident.root_cause_node,
            "primary_event":            incident.primary_event,
            "secondary_affected_count": len(incident.secondary_nodes),
            "secondary_nodes":          incident.secondary_nodes,
            "raw_log_count":            incident.raw_log_count,
            "created_at":               incident.created_at.isoformat(),
        }
        httpx.post(
            self._url,
            json=payload,
            headers=self._headers,
            timeout=self._timeout,
        ).raise_for_status()
