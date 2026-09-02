"""Slack Block Kit 形式の通知。Slack Incoming Webhook URL へ送信する。"""
from __future__ import annotations

import httpx

from topology_syslog.models import Incident
from topology_syslog.notification.base import BaseNotifier, NotificationEvent


class SlackNotifier(BaseNotifier):
    def __init__(self, webhook_url: str, *, timeout: float = 10.0) -> None:
        self._url = webhook_url
        self._timeout = timeout

    def send(self, incident: Incident) -> None:
        self.send_lifecycle(incident, NotificationEvent.NEW)

    def send_lifecycle(self, incident: Incident, event: NotificationEvent) -> None:
        httpx.post(
            self._url,
            json=_build_payload(incident, event),
            timeout=self._timeout,
        ).raise_for_status()


def _build_payload(incident: Incident, event: NotificationEvent = NotificationEvent.NEW) -> dict:
    affected = ", ".join(incident.secondary_nodes) if incident.secondary_nodes else "なし"
    title = {
        NotificationEvent.NEW: "インシデント検知",
        NotificationEvent.UPDATED: "インシデント更新",
        NotificationEvent.RECOVERING: "復旧確認中",
        NotificationEvent.RECOVERED: "復旧検知",
        NotificationEvent.FLAPPING: "フラッピング検知",
    }.get(event, "インシデント更新")
    return {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{title}: {incident.incident_id}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*根本原因:*\n{incident.root_cause_node}"},
                    {"type": "mrkdwn", "text": f"*状態:*\n{incident.condition}"},
                    {"type": "mrkdwn", "text": f"*影響ノード数:*\n{len(incident.secondary_nodes)}"},
                    {"type": "mrkdwn", "text": f"*主イベント:*\n`{incident.primary_event}`"},
                    {"type": "mrkdwn", "text": f"*ログ件数:*\n{incident.raw_log_count}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*二次影響ノード:* {affected}"},
            },
        ]
    }
