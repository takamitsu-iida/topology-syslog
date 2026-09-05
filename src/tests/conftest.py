"""共通フィクスチャ。"""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app
from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader

POC_TOPOLOGY = {
    "network-model": {
        "physical-layer": {
            "device": [
                {
                    "device-id": "Core-Router1",
                    "role": "core",
                    "interface": [{"interface-id": "GE0/0"}],
                },
                {
                    "device-id": "Dist-Switch1",
                    "role": "distribution",
                    "interface": [{"interface-id": "GE0/0"}, {"interface-id": "GE0/1"}],
                },
                {
                    "device-id": "Access-SW1",
                    "role": "access",
                    "interface": [{"interface-id": "GE0/0"}],
                },
                {
                    "device-id": "Branch-Router2",
                    "role": "core",
                    "interface": [{"interface-id": "GE0/0"}],
                },
                {
                    "device-id": "Branch-Access-SW1",
                    "role": "access",
                    "interface": [{"interface-id": "GE0/0"}],
                },
            ],
            "physical-connection": [
                {"endpoint": [{"device-id": "Core-Router1", "interface-id": "GE0/0"}, {"device-id": "Dist-Switch1", "interface-id": "GE0/0"}]},
                {"endpoint": [{"device-id": "Dist-Switch1", "interface-id": "GE0/1"}, {"device-id": "Access-SW1", "interface-id": "GE0/0"}]},
                {"endpoint": [{"device-id": "Branch-Router2", "interface-id": "GE0/0"}, {"device-id": "Branch-Access-SW1", "interface-id": "GE0/0"}]},
            ],
        }
    }
}


@pytest.fixture
def poc_engine() -> GraphEngine:
    loader = TopologyLoader()
    return GraphEngine(loader.load_from_dict(POC_TOPOLOGY))


@pytest.fixture
def poc_topology_file(tmp_path) -> str:
        path = tmp_path / "poc_topology.yaml"
        path.write_text(yaml.safe_dump(POC_TOPOLOGY, sort_keys=False), encoding="utf-8")
        return str(path)


@pytest.fixture
def app(poc_topology_file: str):
    return create_app(
        database_url="sqlite:///:memory:",
        topology_path=poc_topology_file,
        topology_source="iida-yaml",
    )


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
