"""Notifier 抽象基底クラス。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from topology_syslog.models import Incident


class BaseNotifier(ABC):
    @abstractmethod
    def send(self, incident: Incident) -> None:
        """インシデントを通知する。送信失敗時は例外を送出する。"""
