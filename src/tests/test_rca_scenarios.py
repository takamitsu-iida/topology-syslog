import time
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from topology_syslog.api.main import create_app


@dataclass(frozen=True)
class FabricScenario:
    name: str
    topology_path: str
    impact_down: str
    impact_up: str
    child_object: str


SCENARIOS = (
    FabricScenario(
        name="ospf",
        topology_path="configs/ospf/yang_topology.yaml",
        impact_down=(
            "%OSPF-5-ADJCHG: Process 1, Nbr 10.0.0.1 on GigabitEthernet0/0 "
            "from FULL to DOWN, Neighbor Down: Interface down or detached"
        ),
        impact_up=(
            "%OSPF-5-ADJCHG: Process 1, Nbr 10.0.0.1 on GigabitEthernet0/0 "
            "from LOADING to FULL, Loading Done"
        ),
        child_object="OSPFSession:Spine1-Leaf3-OSPF",
    ),
    FabricScenario(
        name="bgp",
        topology_path="configs/clos/yang_topology.yaml",
        impact_down="%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down BGP Notification sent",
        impact_up="%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Up",
        child_object="BGPSession:Spine1-Leaf3-eBGP",
    ),
)


def _raw(hostname: str, timestamp: str, message: str) -> dict[str, str]:
    return {
        "source_ip": "127.0.0.1",
        "raw": f"<35>Sep 7 {timestamp} {hostname} {message}",
    }


def _fault_messages(scenario: FabricScenario) -> list[dict[str, str]]:
    return [
        _raw("Leaf3", "06:11:20.223", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"),
        _raw("Spine1", "06:11:20.233", "%LINK-3-UPDOWN: Interface GigabitEthernet0/2, changed state to down"),
        _raw("Leaf3", "06:11:21.224", scenario.impact_down),
    ]


def _recovery_messages(scenario: FabricScenario) -> list[dict[str, str]]:
    return [
        _raw("Leaf3", "06:12:20.223", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to up"),
        _raw("Spine1", "06:12:20.233", "%LINK-3-UPDOWN: Interface GigabitEthernet0/2, changed state to up"),
        _raw("Leaf3", "06:12:21.224", scenario.impact_up),
    ]


def _new_client(
    tmp_path,
    scenario: FabricScenario,
    *,
    recovery_quiet_period_sec: float = 0.01,
) -> tuple[object, TestClient]:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / f'{scenario.name}.db'}",
        topology_path=scenario.topology_path,
        topology_source="iida-yaml",
        knowledge_path="configs/syslog_knowledge",
        recovery_quiet_period_sec=recovery_quiet_period_sec,
        syslog_port=0,
    )
    return app, TestClient(app)


def _root_and_child(incidents: list[dict]) -> tuple[dict, dict]:
    roots = [incident for incident in incidents if incident["relationship_type"] == "root"]
    children = [incident for incident in incidents if incident["relationship_type"] == "impact"]
    assert len(roots) == 1
    assert len(children) == 1
    return roots[0], children[0]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
@pytest.mark.parametrize(
    "arrival_order",
    (
        (0, 1, 2),
        (2, 0, 1),
        (1, 2, 0),
    ),
    ids=("links-before-impact", "impact-first", "mixed"),
)
def test_fault_order_converges_to_one_parent_and_child(tmp_path, scenario, arrival_order):
    app, client = _new_client(tmp_path, scenario)
    messages = _fault_messages(scenario)

    with client:
        for index in arrival_order:
            response = client.post("/ingest", json={"messages": [messages[index]]})
            assert response.status_code == 200
        incidents = client.get("/incidents?include_children=true").json()["incidents"]

    parent, child = _root_and_child(incidents)
    assert parent["root_cause_object"] == (
        "PhysicalLink:Leaf3:GigabitEthernet0/0--Spine1:GigabitEthernet0/2"
    )
    assert parent["child_incident_ids"] == [child["incident_id"]]
    assert child["parent_incident_id"] == parent["incident_id"]
    assert child["root_cause_object"] == scenario.child_object


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_duplicate_delivery_is_idempotent(tmp_path, scenario):
    app, client = _new_client(tmp_path, scenario)
    messages = _fault_messages(scenario)

    with client:
        for _ in range(2):
            response = client.post("/ingest", json={"messages": messages})
            assert response.status_code == 200
        incidents = client.get("/incidents?include_children=true").json()["incidents"]

    parent, child = _root_and_child(incidents)
    assert parent["child_incident_ids"] == [child["incident_id"]]
    assert len(parent["raw_logs"]) == len(set(parent["raw_logs"]))


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_full_recovery_then_recurrence_creates_a_new_incident_family(tmp_path, scenario):
    app, client = _new_client(tmp_path, scenario)

    with client:
        client.post("/ingest", json={"messages": _fault_messages(scenario)})
        first_incidents = client.get("/incidents?include_children=true").json()["incidents"]
        first_parent, first_child = _root_and_child(first_incidents)

        recovery = client.post("/ingest", json={"messages": _recovery_messages(scenario)})
        assert recovery.status_code == 200
        time.sleep(0.05)
        assert app.state.store.get_by_id(first_parent["incident_id"]).condition == "RECOVERED"
        assert app.state.store.get_by_id(first_child["incident_id"]).condition == "RECOVERED"

        recurrence = client.post("/ingest", json={"messages": _fault_messages(scenario)})
        assert recurrence.status_code == 200
        incidents = client.get("/incidents?include_children=true").json()["incidents"]

    roots = [incident for incident in incidents if incident["relationship_type"] == "root"]
    children = [incident for incident in incidents if incident["relationship_type"] == "impact"]
    assert len(roots) == 2
    assert len(children) == 2
    assert {incident["condition"] for incident in roots} == {"ACTIVE", "RECOVERED"}
    assert {incident["condition"] for incident in children} == {"ACTIVE", "RECOVERED"}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_fault_during_recovery_cancels_stale_recovery_result(tmp_path, scenario):
    app, client = _new_client(tmp_path, scenario, recovery_quiet_period_sec=0.1)

    with client:
        client.post("/ingest", json={"messages": _fault_messages(scenario)})
        incidents = client.get("/incidents?include_children=true").json()["incidents"]
        parent, child = _root_and_child(incidents)

        client.post("/ingest", json={"messages": _recovery_messages(scenario)})
        client.post("/ingest", json={"messages": _fault_messages(scenario)})
        time.sleep(0.15)

        active_parent = app.state.store.get_by_id(parent["incident_id"])
        active_child = app.state.store.get_by_id(child["incident_id"])

    assert active_parent is not None and active_parent.condition == "ACTIVE"
    assert active_child is not None and active_child.condition == "ACTIVE"