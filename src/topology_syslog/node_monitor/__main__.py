"""node-monitor サービス起動入口。"""
from __future__ import annotations

import logging
import os

import uvicorn

from topology_syslog.node_monitor.api import create_app
from topology_syslog.node_monitor.probes import IcmpProbe, TcpProbe
from topology_syslog.node_monitor.scheduler import NodeMonitor
from topology_syslog.node_monitor.store import InMemoryNodeStateStore
from topology_syslog.node_monitor.topology import resolve_monitor_targets
from topology_syslog.node_monitor.webhook import WebhookEventPublisher
from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader


def _targets_from_env(value: str) -> dict[str, str]:
    targets: dict[str, str] = {}
    if not value.strip():
        return targets
    for entry in value.split(","):
        node_id, separator, address = entry.strip().partition("=")
        if not separator or not node_id or not address:
            raise ValueError("NODE_MONITOR_TARGETS must use node_id=ip entries")
        targets[node_id] = address
    return targets


def _targets_from_topology(path: str, source: str) -> dict[str, str]:
    loader = TopologyLoader()
    graph = (
        loader.load_from_iida_json(path)
        if source == "ietf-json"
        else loader.load_from_iida_yaml(path)
    )
    return resolve_monitor_targets(GraphEngine(graph))


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "info").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )
    tcp_ports = [int(port) for port in os.getenv("NODE_MONITOR_TCP_PORTS", "179").split(",") if port]
    monitor = NodeMonitor(
        InMemoryNodeStateStore(),
        (IcmpProbe(float(os.getenv("NODE_MONITOR_PROBE_TIMEOUT_SEC", "2"))),
         *(TcpProbe(port, float(os.getenv("NODE_MONITOR_PROBE_TIMEOUT_SEC", "2"))) for port in tcp_ports)),
        ttl_sec=float(os.getenv("NODE_MONITOR_TTL_SEC", "60")),
        min_check_interval_sec=float(os.getenv("NODE_MONITOR_MIN_CHECK_INTERVAL_SEC", "5")),
        max_failure_backoff_sec=float(os.getenv("NODE_MONITOR_MAX_FAILURE_BACKOFF_SEC", "300")),
        max_concurrent_checks=int(os.getenv("NODE_MONITOR_MAX_CONCURRENT_CHECKS", "10")),
    )
    topology_path = os.getenv("NODE_MONITOR_TOPOLOGY_PATH")
    topology_source = os.getenv("NODE_MONITOR_TOPOLOGY_SOURCE", "iida-yaml")
    targets = (
        _targets_from_topology(topology_path, topology_source)
        if topology_path
        else _targets_from_env(os.getenv("NODE_MONITOR_TARGETS", ""))
    )
    for node_id, address in targets.items():
        monitor.register_target(node_id, address)

    publisher = None
    event_url = os.getenv("NODE_MONITOR_EVENT_URL")
    if event_url:
        publisher = WebhookEventPublisher(
            event_url,
            token=os.getenv("NODE_MONITOR_EVENT_TOKEN", ""),
            timeout_sec=float(os.getenv("NODE_MONITOR_EVENT_TIMEOUT_SEC", "2")),
            max_retries=int(os.getenv("NODE_MONITOR_EVENT_MAX_RETRIES", "3")),
            queue_size=int(os.getenv("NODE_MONITOR_EVENT_QUEUE_SIZE", "1000")),
        )
        monitor._on_state_change = publisher.publish

    app = create_app(
            monitor,
            interval_sec=float(os.getenv("NODE_MONITOR_INTERVAL_SEC", "30")),
            auth_token=os.getenv("NODE_MONITOR_API_TOKEN") or None,
            on_startup=publisher.start if publisher else None,
            on_shutdown=publisher.close if publisher else None,
        )
    uvicorn.run(
        app,
        host=os.getenv("NODE_MONITOR_HOST", "0.0.0.0"),
        port=int(os.getenv("NODE_MONITOR_PORT", "8090")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()