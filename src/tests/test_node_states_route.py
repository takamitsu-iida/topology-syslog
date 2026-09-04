from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app
from topology_syslog.node_monitor.models import NodeState, NodeStateRecord


class _Reader:
    def get_many(self, node_ids: list[str]):
        now = datetime.now(tz=timezone.utc)
        return [NodeStateRecord(node_id, NodeState.UP, now, now + timedelta(minutes=1), "probe succeeded") for node_id in node_ids]


def test_backend_proxies_node_states_for_loaded_topology(app):
    with TestClient(app) as client:
        app.state.node_state_reader = _Reader()
        response = client.get("/node-states")

    assert response.status_code == 200
    assert {state["node_id"] for state in response.json()} >= {"Core-Router1", "Dist-Switch1"}
    assert {state["state"] for state in response.json()} == {"UP"}