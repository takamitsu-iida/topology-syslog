"""Notifier 抽象基底クラス。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from topology_syslog.models import Incident


class NotificationEvent(StrEnum):
    NEW = "incident.new"
    UPDATED = "incident.updated"
    RECOVERING = "incident.recovering"
    RECOVERED = "incident.recovered"
    FLAPPING = "incident.flapping"


class BaseNotifier(ABC):
    @abstractmethod
    def send(self, incident: Incident) -> None:
        """インシデントを通知する。送信失敗時は例外を送出する。"""

    def send_lifecycle(self, incident: Incident, event: NotificationEvent) -> None:
        """状態遷移通知。既存実装は新規通知のみでも動くようデフォルト no-op。"""
        if event == NotificationEvent.NEW:
            self.send(incident)
