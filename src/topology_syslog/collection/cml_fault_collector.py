"""Inject CML faults and persist labeled SYSLOG samples as JSON Lines."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

from topology_syslog.topology.causal_topology import InterfaceEndpoint, physical_link_object_id


@dataclass(frozen=True)
class FaultTarget:
    fault_type: str
    target_id: str
    ground_truth_object: str
    ground_truth_nodes: tuple[str, ...]
    endpoints: tuple[str, ...] = ()


def load_fault_targets(topology_path: str | Path) -> list[FaultTarget]:
    """Load injectable data-plane nodes and links from an iida topology."""
    with Path(topology_path).open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    physical = raw.get("network-model", {}).get("physical-layer", {})

    targets = [
        FaultTarget(
            fault_type="node",
            target_id=device["device-id"],
            ground_truth_object=f"Device:{device['device-id']}",
            ground_truth_nodes=(device["device-id"],),
        )
        for device in physical.get("device", [])
        if device.get("device-id")
    ]

    for connection in physical.get("physical-connection", []):
        connection_id = connection.get("connection-id")
        endpoints = connection.get("endpoint", [])
        if not connection_id or len(endpoints) != 2:
            raise ValueError(
                "Each injectable physical-connection requires a connection-id and two endpoints"
            )
        parsed = tuple(
            InterfaceEndpoint(
                device_id=endpoint["device-id"],
                interface_id=endpoint["interface-id"],
            )
            for endpoint in endpoints
        )
        targets.append(FaultTarget(
            fault_type="link",
            target_id=connection_id,
            ground_truth_object=physical_link_object_id(parsed[0], parsed[1]),
            ground_truth_nodes=tuple(endpoint.device_id for endpoint in parsed),
            endpoints=tuple(
                f"{endpoint.device_id}:{endpoint.interface_id}" for endpoint in parsed
            ),
        ))
    if not targets:
        raise ValueError(f"No injectable targets found in {topology_path}")
    return targets


class FaultController(Protocol):
    def validate_targets(self, targets: Sequence[FaultTarget]) -> None: ...

    def assert_started(self, target: FaultTarget) -> None: ...

    def stop(self, target: FaultTarget) -> None: ...

    def start(self, target: FaultTarget) -> None: ...


class Virl2FaultController:
    """Small adapter around virl2_client objects."""

    def __init__(self, lab: Any) -> None:
        self._lab = lab

    def _element(self, target: FaultTarget) -> Any:
        if target.fault_type == "node":
            return self._lab.get_node_by_label(target.target_id)
        matches = [link for link in self._lab.links() if link.label == target.target_id]
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one CML link labeled {target.target_id!r}, found {len(matches)}"
            )
        return matches[0]

    def validate_targets(self, targets: Sequence[FaultTarget]) -> None:
        for target in targets:
            self._element(target)

    def assert_started(self, target: FaultTarget) -> None:
        state = str(self._element(target).state or "").upper()
        if state != "STARTED":
            raise RuntimeError(f"{target.fault_type} {target.target_id} is not STARTED: {state}")

    def stop(self, target: FaultTarget) -> None:
        self._element(target).stop(wait=False)

    def start(self, target: FaultTarget) -> None:
        self._element(target).start(wait=False)


class BackendClient:
    """Read SKB-classified logs and RCA results from topology-syslog."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def check_ready(self) -> dict[str, Any]:
        response = self._client.get("/debug/status")
        response.raise_for_status()
        status = response.json()
        if not status.get("topology_loaded"):
            raise RuntimeError("topology-syslog API has no topology loaded")
        return status

    def latest_log_id(self) -> int:
        response = self._client.get("/raw-logs", params={"limit": 1})
        response.raise_for_status()
        logs = response.json()["logs"]
        return int(logs[0]["log_id"]) if logs else 0

    def logs_after(self, log_id: int) -> list[dict[str, Any]]:
        logs: list[dict[str, Any]] = []
        cursor = log_id
        while True:
            response = self._client.get(
                "/raw-logs",
                params={"after_id": cursor, "limit": 500},
            )
            response.raise_for_status()
            page = response.json()["logs"]
            logs.extend(page)
            if not page or len(page) < 500:
                return logs
            cursor = int(page[-1]["log_id"])

    def incidents_since(self, started_at: datetime) -> list[dict[str, Any]]:
        response = self._client.get("/incidents", params={"include_children": "true"})
        response.raise_for_status()
        incidents = response.json()["incidents"]
        return [
            incident
            for incident in incidents
            if _parse_timestamp(incident.get("last_fault_at") or incident["created_at"])
            >= started_at
        ]


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class JsonlSampleWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def completed_count(self) -> int:
        return self.counts()[0]

    def counts(self) -> tuple[int, int]:
        if not self.path.exists():
            return 0, 0
        completed = 0
        records = 0
        with self.path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSONL at {self.path}:{line_number}: {exc}"
                    ) from exc
                records += 1
                if record.get("status") == "completed":
                    completed += 1
        return completed, records

    def append(self, sample: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            json.dump(sample, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())


class CMLFaultCollector:
    def __init__(
        self,
        controller: FaultController,
        backend: BackendClient,
        targets: Sequence[FaultTarget],
        writer: JsonlSampleWriter,
        *,
        fault_window_sec: float = 30.0,
        recovery_window_sec: float = 60.0,
        seed: int = 0,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc),
    ) -> None:
        if fault_window_sec < 0 or recovery_window_sec < 0:
            raise ValueError("Collection windows must be non-negative")
        if not targets:
            raise ValueError("At least one fault target is required")
        self._controller = controller
        self._backend = backend
        self._targets = tuple(targets)
        self._writer = writer
        self._fault_window_sec = fault_window_sec
        self._recovery_window_sec = recovery_window_sec
        self._seed = seed
        self._sleep = sleep
        self._now = now

    def run(self, sample_count: int) -> tuple[int, int]:
        if sample_count < 1:
            raise ValueError("sample_count must be at least 1")
        self._backend.check_ready()
        self._controller.validate_targets(self._targets)
        completed, attempts = self._writer.counts()
        failures = 0
        while completed < sample_count:
            sequence = attempts + 1
            target = random.Random(self._seed + sequence).choice(self._targets)
            sample = self._collect_one(sequence, target)
            self._writer.append(sample)
            attempts += 1
            if sample["status"] == "completed":
                completed += 1
            else:
                failures += 1
                print(
                    f"[ERROR] sample {sequence} failed: {sample['error']}",
                    file=sys.stderr,
                    flush=True,
                )
                if failures >= max(10, sample_count):
                    raise RuntimeError(
                        f"Aborting after {failures} failed collection attempts"
                    )
            print(
                f"[{completed}/{sample_count}] {target.fault_type} "
                f"{target.target_id}: {len(sample['fault_logs'])} fault logs, "
                f"{len(sample['recovery_logs'])} recovery logs",
                flush=True,
            )
        return completed, failures

    def _collect_one(self, sequence: int, target: FaultTarget) -> dict[str, Any]:
        sample_id = str(uuid.uuid4())
        baseline_log_id = self._backend.latest_log_id()
        started_at = self._now()
        fault_logs: list[dict[str, Any]] = []
        recovery_logs: list[dict[str, Any]] = []
        incidents: list[dict[str, Any]] = []
        restoration_needed = False
        error: str | None = None

        try:
            self._controller.assert_started(target)
            restoration_needed = True
            self._controller.stop(target)
            self._sleep(self._fault_window_sec)
            fault_logs = self._backend.logs_after(baseline_log_id)
            cursor = (
                int(fault_logs[-1]["log_id"]) if fault_logs else baseline_log_id
            )
            incidents = self._backend.incidents_since(started_at)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if restoration_needed:
                try:
                    self._controller.start(target)
                    self._sleep(self._recovery_window_sec)
                    cursor = (
                        int(fault_logs[-1]["log_id"])
                        if fault_logs
                        else baseline_log_id
                    )
                    recovery_logs = self._backend.logs_after(cursor)
                except Exception as exc:
                    restoration_error = f"{type(exc).__name__}: {exc}"
                    error = (
                        f"{error}; restore failed: {restoration_error}"
                        if error
                        else f"restore failed: {restoration_error}"
                    )

        finished_at = self._now()
        return {
            "schema_version": 1,
            "sample_id": sample_id,
            "sequence": sequence,
            "seed": self._seed,
            "status": "failed" if error else "completed",
            "error": error,
            "fault": asdict(target),
            "timing": {
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "fault_window_sec": self._fault_window_sec,
                "recovery_window_sec": self._recovery_window_sec,
            },
            "baseline_log_id": baseline_log_id,
            "fault_logs": fault_logs,
            "recovery_logs": recovery_logs,
            "incidents": incidents,
            "quality": {
                "has_fault_logs": bool(fault_logs),
                "incident_generated": bool(incidents),
                "all_logs_skb_classified": all(
                    log.get("knowledge_status") in {"known", "unknown"}
                    for log in [*fault_logs, *recovery_logs]
                ),
            },
        }


def _load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() not in {"false", "0", "no"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CML障害をランダム注入し、SKB分類済みSYSLOGと正解ラベルを収集する",
    )
    parser.add_argument("--lab-id", required=True, help="稼働中のCML lab ID")
    parser.add_argument("--samples", type=int, default=1000, help="完了サンプル数")
    parser.add_argument(
        "--output",
        default="data/cml_fault_samples.jsonl",
        help="追記・再開可能なJSONL出力先",
    )
    parser.add_argument(
        "--topology",
        default="configs/ospf/yang_topology.yaml",
        help="注入対象を定義するiida topology",
    )
    parser.add_argument("--api-url", default=None, help="topology-syslog API URL")
    parser.add_argument("--api-token", default=None, help="API reader token")
    parser.add_argument("--fault-window-sec", type=float, default=30.0)
    parser.add_argument("--recovery-window-sec", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _load_env_file()
    args = build_parser().parse_args(argv)
    cml_url = os.environ.get("CML_URL")
    cml_username = os.environ.get("CML_USERNAME")
    cml_password = os.environ.get("CML_PASSWORD")
    missing = [
        name
        for name, value in (
            ("CML_URL", cml_url),
            ("CML_USERNAME", cml_username),
            ("CML_PASSWORD", cml_password),
        )
        if not value
    ]
    if missing:
        print(f"Missing CML settings: {', '.join(missing)}", file=sys.stderr)
        return 2

    try:
        from virl2_client import ClientLibrary
    except ImportError:
        print(
            "virl2-client is required. Install the version compatible with your "
            "CML controller: uv pip install virl2-client",
            file=sys.stderr,
        )
        return 2

    api_url = args.api_url or os.environ.get("COLLECTOR_API_URL", "http://127.0.0.1:8080")
    api_token = args.api_token or os.environ.get("AUTH_READER_TOKEN")
    client = ClientLibrary(
        url=cml_url,
        username=cml_username,
        password=cml_password,
        ssl_verify=_env_bool("CML_VERIFY_SSL", True),
    )
    lab = client.join_existing_lab(args.lab_id)
    backend = BackendClient(api_url, token=api_token)
    try:
        collector = CMLFaultCollector(
            Virl2FaultController(lab),
            backend,
            load_fault_targets(args.topology),
            JsonlSampleWriter(args.output),
            fault_window_sec=args.fault_window_sec,
            recovery_window_sec=args.recovery_window_sec,
            seed=args.seed,
        )
        completed, failures = collector.run(args.samples)
    finally:
        backend.close()
    print(f"Collection complete: {completed} samples, {failures} failed attempts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
