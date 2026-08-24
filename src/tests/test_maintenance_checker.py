"""MaintenanceChecker のユニットテスト。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from topology_syslog.maintenance.checker import (
    MaintenanceChecker,
    MaintenancePlan,
    _AffectedDevice,
    _load_plan_from_dict,
)
from topology_syslog.models import Incident


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 25, 3, 0, 0, tzinfo=timezone.utc)  # 窓の中央


def _plan(
    plan_id: str = "CHG-2026-0001",
    start_offset_h: float = -1.0,
    end_offset_h: float = 1.0,
    status: str = "planned",
    device_ids: list[str] | None = None,
    scope: str = "device-only",
    patterns: list[str] | None = None,
) -> MaintenancePlan:
    return MaintenancePlan(
        plan_id=plan_id,
        title="テスト計画",
        scheduled_start=_NOW + timedelta(hours=start_offset_h),
        scheduled_end=_NOW + timedelta(hours=end_offset_h),
        status=status,
        affected_devices=[
            _AffectedDevice(device_id=d, scope=scope)
            for d in (device_ids or ["Spine1"])
        ],
        expected_patterns=[re.compile(p) for p in (patterns or [])],
    )


def _incident(
    root_cause: str = "Spine1",
    primary_event: str = "%LINK-3-UPDOWN: Interface down",
) -> Incident:
    return Incident(
        incident_id="INC-20260825-001",
        created_at=_NOW,
        root_cause_node=root_cause,
        primary_event=primary_event,
        secondary_nodes=[],
        raw_log_count=1,
    )


# ---------------------------------------------------------------------------
# MaintenancePlan.is_active_at
# ---------------------------------------------------------------------------

def test_is_active_within_window():
    assert _plan().is_active_at(_NOW)


def test_is_active_before_window():
    assert not _plan(start_offset_h=1.0, end_offset_h=2.0).is_active_at(_NOW)


def test_is_active_after_window():
    assert not _plan(start_offset_h=-2.0, end_offset_h=-1.0).is_active_at(_NOW)


def test_is_active_cancelled():
    assert not _plan(status="cancelled").is_active_at(_NOW)


def test_is_active_completed():
    assert not _plan(status="completed").is_active_at(_NOW)


def test_is_active_in_progress():
    assert _plan(status="in-progress").is_active_at(_NOW)


# ---------------------------------------------------------------------------
# MaintenancePlan.covers_device
# ---------------------------------------------------------------------------

def test_covers_device_exact_match():
    assert _plan(device_ids=["Spine1"]).covers_device("Spine1", graph=None)


def test_covers_device_no_match():
    assert not _plan(device_ids=["Spine1"]).covers_device("Leaf1", graph=None)


def test_covers_device_including_links(poc_engine):
    # poc トポロジーで隣接ノードが covering されることを確認
    plan = _plan(device_ids=["Core-Router1"], scope="including-links")
    neighbors = poc_engine.get_direct_neighbors("Core-Router1")
    assert neighbors, "テスト前提: Core-Router1 は隣接ノードを持つ"
    neighbor = neighbors[0]
    assert plan.covers_device(neighbor, graph=poc_engine)


def test_covers_device_including_downstream(poc_engine):
    plan = _plan(device_ids=["Core-Router1"], scope="including-downstream")
    descendants = poc_engine.get_descendants("Core-Router1")
    if descendants:
        assert plan.covers_device(next(iter(descendants)), graph=poc_engine)


def test_covers_device_scope_no_graph_fallback():
    # グラフなしで including-links を指定した場合、device-only と同等の動作
    plan = _plan(device_ids=["Spine1"], scope="including-links")
    assert not plan.covers_device("Leaf1", graph=None)


# ---------------------------------------------------------------------------
# MaintenancePlan.matches_message
# ---------------------------------------------------------------------------

def test_matches_message_no_patterns():
    plan = _plan(patterns=[])
    assert plan.matches_message("anything at all")


def test_matches_message_with_matching_pattern():
    plan = _plan(patterns=[r"%LINK-3-UPDOWN", r"%BGP-5-ADJCHG"])
    assert plan.matches_message("%LINK-3-UPDOWN: Interface GE0/0 down")


def test_matches_message_no_matching_pattern():
    plan = _plan(patterns=[r"%BGP-5-ADJCHG"])
    assert not plan.matches_message("%SYS-5-CONFIG_I: Configured from console")


# ---------------------------------------------------------------------------
# _load_plan_from_dict
# ---------------------------------------------------------------------------

def test_load_plan_from_dict_minimal():
    raw = {
        "plan-id": "CHG-2026-0099",
        "title": "最小構成テスト",
        "scheduled-start": "2026-08-25T02:00:00+09:00",
        "scheduled-end": "2026-08-25T04:00:00+09:00",
        "affected-device": [{"device-id": "Spine1"}],
    }
    plan = _load_plan_from_dict(raw)
    assert plan is not None
    assert plan.plan_id == "CHG-2026-0099"
    assert plan.status == "planned"
    assert plan.scheduled_start.tzinfo is not None
    assert len(plan.affected_devices) == 1
    assert plan.affected_devices[0].device_id == "Spine1"
    assert plan.expected_patterns == []


def test_load_plan_from_dict_missing_required_key():
    raw = {"plan-id": "CHG-2026-0099"}  # title / scheduled-start 欠如
    plan = _load_plan_from_dict(raw)
    assert plan is None


# ---------------------------------------------------------------------------
# MaintenanceChecker (ファイルベース)
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, content: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(content, f, allow_unicode=True)


@pytest.fixture
def maint_dir(tmp_path: Path) -> Path:
    return tmp_path / "maintenance"


def _yaml_content(plan_id: str, start: str, end: str, device_id: str = "Spine1") -> dict:
    return {
        "maintenance-plans": {
            "plan": [
                {
                    "plan-id": plan_id,
                    "title": f"{plan_id} テスト",
                    "scheduled-start": start,
                    "scheduled-end": end,
                    "status": "planned",
                    "affected-device": [{"device-id": device_id}],
                }
            ]
        }
    }


def test_checker_loads_yaml(maint_dir: Path):
    maint_dir.mkdir()
    _write_yaml(
        maint_dir / "CHG-2026-0001.yaml",
        _yaml_content("CHG-2026-0001", "2026-08-25T02:00:00+00:00", "2026-08-25T04:00:00+00:00"),
    )
    checker = MaintenanceChecker(maint_dir)
    inc = _incident()
    result = checker.find_active_plan(inc, at=_NOW)
    assert result is not None
    assert result.plan_id == "CHG-2026-0001"


def test_checker_no_match_outside_window(maint_dir: Path):
    maint_dir.mkdir()
    _write_yaml(
        maint_dir / "CHG-2026-0001.yaml",
        _yaml_content("CHG-2026-0001", "2026-08-26T02:00:00+00:00", "2026-08-26T04:00:00+00:00"),
    )
    checker = MaintenanceChecker(maint_dir)
    result = checker.find_active_plan(_incident(), at=_NOW)
    assert result is None


def test_checker_no_match_wrong_device(maint_dir: Path):
    maint_dir.mkdir()
    _write_yaml(
        maint_dir / "CHG-2026-0001.yaml",
        _yaml_content("CHG-2026-0001", "2026-08-25T02:00:00+00:00", "2026-08-25T04:00:00+00:00", device_id="Spine2"),
    )
    checker = MaintenanceChecker(maint_dir)
    result = checker.find_active_plan(_incident(root_cause="Spine1"), at=_NOW)
    assert result is None


def test_checker_pattern_suppresses(maint_dir: Path):
    maint_dir.mkdir()
    content = _yaml_content("CHG-2026-0001", "2026-08-25T02:00:00+00:00", "2026-08-25T04:00:00+00:00")
    content["maintenance-plans"]["plan"][0]["expected-syslog-pattern"] = [r"%LINK-3-UPDOWN"]
    _write_yaml(maint_dir / "CHG-2026-0001.yaml", content)
    checker = MaintenanceChecker(maint_dir)
    inc = _incident(primary_event="%LINK-3-UPDOWN: Interface down")
    assert checker.find_active_plan(inc, at=_NOW) is not None


def test_checker_pattern_not_matching(maint_dir: Path):
    maint_dir.mkdir()
    content = _yaml_content("CHG-2026-0001", "2026-08-25T02:00:00+00:00", "2026-08-25T04:00:00+00:00")
    content["maintenance-plans"]["plan"][0]["expected-syslog-pattern"] = [r"%BGP-5-ADJCHG"]
    _write_yaml(maint_dir / "CHG-2026-0001.yaml", content)
    checker = MaintenanceChecker(maint_dir)
    inc = _incident(primary_event="%SYS-5-CONFIG_I: Configured from console")
    assert checker.find_active_plan(inc, at=_NOW) is None


def test_checker_empty_dir(maint_dir: Path):
    maint_dir.mkdir()
    checker = MaintenanceChecker(maint_dir)
    assert checker.find_active_plan(_incident(), at=_NOW) is None


def test_checker_nonexistent_dir(tmp_path: Path):
    checker = MaintenanceChecker(tmp_path / "nonexistent")
    assert checker.find_active_plan(_incident(), at=_NOW) is None


def test_checker_reload_if_changed(maint_dir: Path):
    maint_dir.mkdir()
    checker = MaintenanceChecker(maint_dir)
    assert checker.find_active_plan(_incident(), at=_NOW) is None

    # ファイルを追加後 reload_if_changed を呼ぶと検知される
    _write_yaml(
        maint_dir / "CHG-2026-0001.yaml",
        _yaml_content("CHG-2026-0001", "2026-08-25T02:00:00+00:00", "2026-08-25T04:00:00+00:00"),
    )
    checker.reload_if_changed()
    assert checker.find_active_plan(_incident(), at=_NOW) is not None
