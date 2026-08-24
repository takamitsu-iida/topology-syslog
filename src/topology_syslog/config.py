from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class SyslogConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 514
    protocol: str = "udp"  # udp | tcp | tls


@dataclass
class CorrelationConfig:
    window_sec: int = 30
    max_buffer_size: int = 100_000


@dataclass
class TopologyConfig:
    source: str = "ietf-json"  # ietf-json | iida-yaml | netconf
    path: str = "topology/l3_topology.json"


@dataclass
class StorageConfig:
    database_url: str = "sqlite:///./incidents.db"


@dataclass
class ApiConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class MaintenanceConfig:
    dir: str = "configs/maintenance"


@dataclass
class AppConfig:
    syslog: SyslogConfig = field(default_factory=SyslogConfig)
    correlation: CorrelationConfig = field(default_factory=CorrelationConfig)
    topology: TopologyConfig = field(default_factory=TopologyConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    maintenance: MaintenanceConfig = field(default_factory=MaintenanceConfig)


def load_config(path: str | None = None) -> AppConfig:
    cfg = AppConfig()
    if path and os.path.exists(path):
        with open(path) as f:
            raw: dict = yaml.safe_load(f) or {}
        _apply(cfg, raw)
    return cfg


def _apply(cfg: AppConfig, raw: dict) -> None:
    if s := raw.get("syslog"):
        cfg.syslog.listen_host = s.get("listen_host", cfg.syslog.listen_host)
        cfg.syslog.listen_port = s.get("listen_port", cfg.syslog.listen_port)
        cfg.syslog.protocol = s.get("protocol", cfg.syslog.protocol)
    if c := raw.get("correlation"):
        cfg.correlation.window_sec = c.get("window_sec", cfg.correlation.window_sec)
        cfg.correlation.max_buffer_size = c.get("max_buffer_size", cfg.correlation.max_buffer_size)
    if t := raw.get("topology"):
        cfg.topology.source = t.get("source", cfg.topology.source)
        cfg.topology.path = t.get("path", cfg.topology.path)
    if s := raw.get("storage"):
        cfg.storage.database_url = s.get("database_url", cfg.storage.database_url)
    if a := raw.get("api"):
        cfg.api.host = a.get("host", cfg.api.host)
        cfg.api.port = a.get("port", cfg.api.port)
