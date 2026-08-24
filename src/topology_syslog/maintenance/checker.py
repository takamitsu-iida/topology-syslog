"""作業計画書（YAML）を読み込み、インシデントのメンテナンス該当判定を行うモジュール。

configs/maintenance/ ディレクトリ以下の *.yaml を監視し、
ファイルの mtime が変化した場合のみ再読み込みする（ホットリロード）。
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from topology_syslog.models import Incident
    from topology_syslog.topology.graph_engine import GraphEngine

_logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = frozenset({"planned", "in-progress"})


@dataclass
class _AffectedDevice:
    device_id: str
    scope: str = "device-only"  # device-only | including-links | including-downstream
    note: str = ""


@dataclass
class MaintenancePlan:
    plan_id: str
    title: str
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    affected_devices: list[_AffectedDevice] = field(default_factory=list)
    expected_patterns: list[re.Pattern] = field(default_factory=list)  # type: ignore[type-arg]

    def is_active_at(self, at: datetime) -> bool:
        """at 時点でこの計画が有効（scheduled かつ時間内）かどうか。"""
        if self.status not in _ACTIVE_STATUSES:
            return False
        return self.scheduled_start <= at <= self.scheduled_end

    def covers_device(self, device_id: str, graph: "GraphEngine | None") -> bool:
        """device_id がこの計画の抑制対象かどうかを scope を考慮して判定する。"""
        for dev in self.affected_devices:
            if dev.device_id == device_id:
                return True
            if graph is None:
                continue
            if dev.scope == "including-links":
                if device_id in graph.get_direct_neighbors(dev.device_id):
                    return True
            elif dev.scope == "including-downstream":
                if device_id in graph.get_descendants(dev.device_id):
                    return True
        return False

    def matches_message(self, message: str) -> bool:
        """expected_patterns が空なら常に True、あれば 1 件でも一致すれば True。"""
        if not self.expected_patterns:
            return True
        return any(p.search(message) for p in self.expected_patterns)


def _parse_datetime(value: str) -> datetime:
    """RFC 3339 / ISO 8601 文字列を aware datetime に変換する。"""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_plan_from_dict(raw: dict) -> MaintenancePlan | None:
    try:
        plan_id = raw["plan-id"]
        title = raw["title"]
        scheduled_start = _parse_datetime(str(raw["scheduled-start"]))
        scheduled_end = _parse_datetime(str(raw["scheduled-end"]))
        status = str(raw.get("status", "planned"))

        affected_devices = [
            _AffectedDevice(
                device_id=str(dev["device-id"]),
                scope=str(dev.get("scope", "device-only")),
                note=str(dev.get("note", "")),
            )
            for dev in raw.get("affected-device", [])
        ]

        patterns = [
            re.compile(p)
            for p in raw.get("expected-syslog-pattern", [])
        ]

        return MaintenancePlan(
            plan_id=plan_id,
            title=title,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            status=status,
            affected_devices=affected_devices,
            expected_patterns=patterns,
        )
    except (KeyError, ValueError) as exc:
        _logger.warning("作業計画のパースに失敗しました: %s", exc)
        return None


def _load_file(path: Path) -> list[MaintenancePlan]:
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return []
        raw_plans = (data.get("maintenance-plans") or {}).get("plan") or []
        if isinstance(raw_plans, dict):
            raw_plans = [raw_plans]
        plans = []
        for raw in raw_plans:
            plan = _load_plan_from_dict(raw)
            if plan is not None:
                plans.append(plan)
        return plans
    except Exception as exc:
        _logger.warning("作業計画ファイルの読み込みに失敗しました %s: %s", path, exc)
        return []


class MaintenanceChecker:
    """configs/maintenance/ ディレクトリを監視し、インシデントの抑制判定を行う。"""

    def __init__(self, maintenance_dir: str | Path) -> None:
        self._dir = Path(maintenance_dir)
        self._plans: list[MaintenancePlan] = []
        self._mtimes: dict[str, float] = {}
        self._lock = threading.Lock()
        self._reload_all()

    # ------------------------------------------------------------------
    # ホットリロード
    # ------------------------------------------------------------------

    def reload_if_changed(self) -> None:
        """ディレクトリ内の *.yaml の mtime を確認し、変更があれば再読み込みする。"""
        if not self._dir.is_dir():
            return
        current_files = {str(p) for p in self._dir.glob("*.yaml")}
        known_files = set(self._mtimes.keys())

        changed = False
        for path_str in current_files | known_files:
            p = Path(path_str)
            if not p.exists():
                changed = True
                break
            mtime = p.stat().st_mtime
            if self._mtimes.get(path_str) != mtime:
                changed = True
                break

        if changed:
            _logger.info("作業計画ファイルの変更を検知しました。再読み込みします。")
            self._reload_all()

    def _reload_all(self) -> None:
        if not self._dir.is_dir():
            _logger.debug("メンテナンスディレクトリが存在しません: %s", self._dir)
            return
        new_plans: list[MaintenancePlan] = []
        new_mtimes: dict[str, float] = {}
        for path in sorted(self._dir.glob("*.yaml")):
            new_mtimes[str(path)] = path.stat().st_mtime
            loaded = _load_file(path)
            new_plans.extend(loaded)
            _logger.debug("読み込み完了: %s (%d 件)", path.name, len(loaded))
        with self._lock:
            self._plans = new_plans
            self._mtimes = new_mtimes
        _logger.info(
            "作業計画を %d ファイルから %d 件読み込みました (%s)",
            len(new_mtimes), len(new_plans), self._dir,
        )

    # ------------------------------------------------------------------
    # インシデント判定
    # ------------------------------------------------------------------

    def find_active_plan(
        self,
        incident: "Incident",
        at: datetime,
        graph: "GraphEngine | None" = None,
    ) -> MaintenancePlan | None:
        """incident の root_cause_node がメンテナンス中なら該当計画を返す。

        - scheduled_start <= at <= scheduled_end かつ status が planned/in-progress
        - scope に応じてグラフ隣接ノードも対象に含める
        - expected_syslog_pattern が指定されていれば primary_event との照合も行う
        """
        with self._lock:
            plans = list(self._plans)

        for plan in plans:
            if not plan.is_active_at(at):
                continue
            if not plan.covers_device(incident.root_cause_node, graph):
                continue
            if not plan.matches_message(incident.primary_event):
                continue
            return plan
        return None
