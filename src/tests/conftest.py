"""共通フィクスチャ。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app
from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader

_ROOT = Path(__file__).parent.parent.parent  # topology-syslog/
POC_JSON = str(_ROOT / "poc" / "topology" / "l3_topology.json")


@pytest.fixture
def poc_engine() -> GraphEngine:
    loader = TopologyLoader()
    return GraphEngine(loader.load_from_iida_json(POC_JSON))


@pytest.fixture
def app():
    return create_app(
        database_url="sqlite:///:memory:",
        topology_path=POC_JSON,
        topology_source="ietf-json",
    )


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
