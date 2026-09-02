"""vigil の /api/v1/alerts へインシデントを転送する。"""
from __future__ import annotations

import logging

import httpx

from topology_syslog.models import Incident
from topology_syslog.notification.base import BaseNotifier

_logger = logging.getLogger(__name__)


class VigilNotifier(BaseNotifier):
    def __init__(
        self,
        base_url: str,
        *,
        team_name: str = "default",
        default_priority: str = "P3",
        timeout: float = 10.0,
    ) -> None:
        self._api_base = base_url.rstrip("/") + "/api/v1"
        self._url = self._api_base + "/alerts"
        self._team_name = team_name
        self._default_priority = default_priority
        self._timeout = timeout
        self._sent_alerts: set[str] = set()

    def send(self, incident: Incident) -> None:
        fingerprint = f"{incident.incident_id}:{incident.root_cause_node}:{incident.primary_event}"
        if fingerprint in self._sent_alerts:
            _logger.debug("Skip duplicate vigil alert for %s", fingerprint)
            return
        self._sent_alerts.add(fingerprint)

        affected = ", ".join(incident.secondary_nodes) if incident.secondary_nodes else "なし"
        description = f"影響ノード: {affected} / ログ件数: {incident.raw_log_count}"
        if incident.recurrence_count:
            description += f" / 再発: {incident.recurrence_count}回"

        # FLAPPING または再発インシデントは P2 に昇格
        priority = (
            "P2"
            if incident.status == "FLAPPING" or incident.recurrence_count > 0
            else self._default_priority
        )

        httpx.post(
            self._url,
            json={
                "title": f"[{incident.incident_id}] {incident.root_cause_node}: {incident.primary_event}",
                "description": description,
                "source": incident.root_cause_node,
                "team_name": self._team_name,
                "priority": priority,
            },
            timeout=self._timeout,
        ).raise_for_status()

    def resolve_by_source(self, root_cause_node: str) -> None:
        """vigil 側の該当インシデントを RESOLVED にする。失敗してもログのみ。"""
        try:
            httpx.post(
                self._api_base + "/incidents/resolve-by-source",
                json={"source": root_cause_node},
                timeout=self._timeout,
            ).raise_for_status()
        except Exception as exc:
            _logger.warning("vigil resolve-by-source 失敗 (%s): %s", root_cause_node, exc)
