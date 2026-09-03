from __future__ import annotations

import asyncio
import argparse
import os
import sys

import yaml

from topology_syslog.__main__ import _run_ingest
from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
from topology_syslog.ingestion.file_ingest import run_stream
from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader


def _topology_file(tmp_path) -> str:
    path = tmp_path / "topology.yaml"
    path.write_text(yaml.safe_dump({
        "network-model": {
            "physical-layer": {
                "device": [{"device-id": "r1", "role": "core"}],
                "physical-connection": [],
            },
        },
    }), encoding="utf-8")
    return str(path)


def _args(topology: str, ingest: str) -> argparse.Namespace:
    return argparse.Namespace(
        topology=topology,
        ingest=ingest,
        json=False,
        vigil_url="http://vigil.test",
        vigil_team="netops",
    )


def _clear_ingest_environment(monkeypatch) -> None:
    for key in (
        "CORRELATION_MODE", "DATABASE_URL", "MAINTENANCE_DIR",
        "SYSLOG_IGNORE_FILE", "VIGIL_URL", "VIGIL_TEAM",
    ):
        monkeypatch.delenv(key, raising=False)


def test_cli_ingest_with_vigil_url_sends_notification(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "syslog.txt"
    log_path.write_text(
        "<34>Aug 16 10:00:00 r1 %LINK-3-UPDOWN: Interface GE0/0 down\n",
        encoding="utf-8",
    )
    _clear_ingest_environment(monkeypatch)
    sent = []

    class Notifier:
        def send(self, incident):
            sent.append(incident.incident_id)

    monkeypatch.setattr("topology_syslog.notification.vigil.VigilNotifier", lambda *args, **kwargs: Notifier())

    _run_ingest(_args(_topology_file(tmp_path), str(log_path)))

    assert len(sent) == 1
    assert "1 incident(s) found." in capsys.readouterr().err


def test_cli_ingest_continues_when_vigil_notification_fails(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "syslog.txt"
    log_path.write_text(
        "<34>Aug 16 10:00:00 r1 %LINK-3-UPDOWN: Interface GE0/0 down\n",
        encoding="utf-8",
    )
    _clear_ingest_environment(monkeypatch)

    class FailingNotifier:
        def send(self, incident):
            raise OSError("vigil unavailable")

    monkeypatch.setattr("topology_syslog.notification.vigil.VigilNotifier", lambda *args, **kwargs: FailingNotifier())

    _run_ingest(_args(_topology_file(tmp_path), str(log_path)))

    captured = capsys.readouterr()
    assert "[INCIDENT]" in captured.out
    assert "1 incident(s) found." in captured.err


def test_stream_ingest_sends_vigil_notification(monkeypatch):
    read_fd, write_fd = os.pipe()
    with os.fdopen(write_fd, "wb") as writer:
        writer.write(b"<34>Aug 16 10:00:00 r1 %LINK-3-UPDOWN: Interface GE0/0 down\n")
    stream = os.fdopen(read_fd, "r", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stream)
    sent = []

    class Notifier:
        def send(self, incident):
            sent.append(incident.incident_id)

    graph = GraphEngine(TopologyLoader().load_from_dict({
        "network-model": {
            "physical-layer": {"device": [{"device-id": "r1", "role": "core"}]},
        },
    }))
    try:
        count = asyncio.run(run_stream(graph, RootCauseInferencer(), notifier=Notifier()))
    finally:
        stream.close()

    assert count == 1
    assert len(sent) == 1