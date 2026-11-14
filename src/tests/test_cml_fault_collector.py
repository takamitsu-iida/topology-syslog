from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from topology_syslog.collection.cml_fault_collector import (
    CMLFaultCollector,
    FaultTarget,
    JsonlSampleWriter,
    load_fault_targets,
)


class _Controller:
    def __init__(self, *, stop_error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.stop_error = stop_error

    def validate_targets(self, targets) -> None:
        self.calls.append(("validate", str(len(targets))))

    def assert_started(self, target: FaultTarget) -> None:
        self.calls.append(("assert_started", target.target_id))

    def stop(self, target: FaultTarget) -> None:
        self.calls.append(("stop", target.target_id))
        if self.stop_error:
            raise self.stop_error

    def start(self, target: FaultTarget) -> None:
        self.calls.append(("start", target.target_id))


class _Backend:
    def __init__(self) -> None:
        self.log_calls = 0

    def check_ready(self) -> dict:
        return {"topology_loaded": True}

    def latest_log_id(self) -> int:
        return 10

    def logs_after(self, log_id: int) -> list[dict]:
        self.log_calls += 1
        if self.log_calls == 1:
            return [{
                "log_id": 11,
                "message": "fault",
                "knowledge_status": "known",
            }]
        return [{
            "log_id": 12,
            "message": "recovery",
            "knowledge_status": "unknown",
        }]

    def incidents_since(self, started_at: datetime) -> list[dict]:
        return [{"incident_id": "INC-1", "last_fault_at": started_at.isoformat()}]


def _clock():
    current = datetime(2026, 11, 12, tzinfo=timezone.utc)

    def now() -> datetime:
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return now


def test_load_fault_targets_excludes_management_links():
    targets = load_fault_targets("configs/ospf/yang_topology.yaml")

    nodes = [target for target in targets if target.fault_type == "node"]
    links = [target for target in targets if target.fault_type == "link"]
    assert {target.target_id for target in nodes} == {
        "Spine1", "Spine2", "Leaf1", "Leaf2", "Leaf3",
    }
    assert len(links) == 6
    assert all("Management" not in target.target_id for target in links)
    assert all(target.ground_truth_object.startswith("PhysicalLink:") for target in links)


def test_collector_persists_labeled_fault_and_recovery_logs(tmp_path):
    target = FaultTarget("node", "Spine1", "Device:Spine1", ("Spine1",))
    controller = _Controller()
    output = tmp_path / "samples.jsonl"
    collector = CMLFaultCollector(
        controller,
        _Backend(),
        [target],
        JsonlSampleWriter(output),
        fault_window_sec=0,
        recovery_window_sec=0,
        sleep=lambda _seconds: None,
        now=_clock(),
    )

    assert collector.run(1) == (1, 0)

    sample = json.loads(output.read_text(encoding="utf-8"))
    assert sample["status"] == "completed"
    assert sample["fault"]["ground_truth_object"] == "Device:Spine1"
    assert sample["fault_logs"][0]["log_id"] == 11
    assert sample["recovery_logs"][0]["log_id"] == 12
    assert sample["incidents"][0]["incident_id"] == "INC-1"
    assert sample["quality"] == {
        "has_fault_logs": True,
        "incident_generated": True,
        "all_logs_skb_classified": True,
    }
    assert controller.calls[-3:] == [
        ("assert_started", "Spine1"),
        ("stop", "Spine1"),
        ("start", "Spine1"),
    ]


def test_collector_restores_target_when_fault_injection_raises(tmp_path):
    target = FaultTarget("link", "Spine1-Leaf1", "PhysicalLink:x", ("Spine1", "Leaf1"))
    controller = _Controller(stop_error=RuntimeError("CML unavailable"))
    writer = JsonlSampleWriter(tmp_path / "samples.jsonl")
    collector = CMLFaultCollector(
        controller,
        _Backend(),
        [target],
        writer,
        fault_window_sec=0,
        recovery_window_sec=0,
        sleep=lambda _seconds: None,
        now=_clock(),
    )

    with pytest.raises(RuntimeError, match="failed collection attempts"):
        collector.run(1)

    assert ("start", "Spine1-Leaf1") in controller.calls
    records = [
        json.loads(line)
        for line in writer.path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 10
    assert all(record["status"] == "failed" for record in records)


def test_writer_resume_counts_records_and_completed_samples(tmp_path):
    writer = JsonlSampleWriter(tmp_path / "samples.jsonl")
    writer.append({"status": "failed"})
    writer.append({"status": "completed"})

    assert writer.counts() == (1, 2)
