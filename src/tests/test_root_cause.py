from datetime import datetime, timezone

import pytest

from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
from topology_syslog.models import SyslogMessage


def _msg(hostname: str, message: str = "test event") -> SyslogMessage:
    return SyslogMessage(
        received_at=datetime.now(tz=timezone.utc),
        source_ip="10.0.0.1",
        hostname=hostname,
        facility=3,
        severity=3,
        message=message,
    )


def test_3node_chain_single_incident(poc_engine):
    msgs = [
        _msg("Core-Router1", "%LINK-3-UPDOWN: Interface GE0/0 down"),
        _msg("Dist-Switch1",  "%BGP-5-ADJCHANGE: neighbor down"),
        _msg("Access-SW1",    "%PING-3-FAILED: gateway unreachable"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.root_cause_node == "Core-Router1"
    assert set(inc.secondary_nodes) == {"Dist-Switch1", "Access-SW1"}
    assert inc.raw_log_count == 3
    assert inc.status == "OPEN"


def test_noise_separation_yields_two_incidents(poc_engine):
    msgs = [
        _msg("Core-Router1", "%LINK-3-UPDOWN: Interface GE0/0 down"),
        _msg("Dist-Switch1",  "%BGP-5-ADJCHANGE: neighbor down"),
        _msg("Access-SW1",    "%PING-3-FAILED: gateway unreachable"),
        _msg("Branch-Router2", "%LINK-3-UPDOWN: WAN interface down"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert len(incidents) == 2
    root_causes = {i.root_cause_node for i in incidents}
    assert "Core-Router1" in root_causes
    assert "Branch-Router2" in root_causes


def test_branch_chain_secondary(poc_engine):
    """Branch-Router2 と Branch-Access-SW1 が連鎖する場合。"""
    msgs = [
        _msg("Branch-Router2",    "%LINK-3-UPDOWN: WAN down"),
        _msg("Branch-Access-SW1", "%CDP-4-NATIVE_VLAN_MISMATCH: vlan mismatch"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert len(incidents) == 1
    assert incidents[0].root_cause_node == "Branch-Router2"
    assert incidents[0].secondary_nodes == ["Branch-Access-SW1"]


def test_unknown_host_excluded(poc_engine):
    msgs = [
        _msg("Core-Router1", "link down"),
        _msg("UnknownDevice", "some error"),
    ]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert all(i.root_cause_node != "UnknownDevice" for i in incidents)
    assert all("UnknownDevice" not in i.secondary_nodes for i in incidents)


def test_empty_messages_returns_empty(poc_engine):
    assert RootCauseInferencer().infer([], poc_engine) == []


def test_all_unknown_returns_empty(poc_engine):
    msgs = [_msg("Ghost1"), _msg("Ghost2")]
    assert RootCauseInferencer().infer(msgs, poc_engine) == []


def test_incident_id_format(poc_engine):
    msgs = [_msg("Core-Router1", "link down")]
    incidents = RootCauseInferencer().infer(msgs, poc_engine)
    assert incidents[0].incident_id.startswith("INC-")
    parts = incidents[0].incident_id.split("-")
    assert len(parts) == 3
    assert parts[1].isdigit() and len(parts[1]) == 8  # YYYYMMDD
    assert parts[2].isdigit() and len(parts[2]) == 3  # NNN


def test_incident_counter_increments(poc_engine):
    inferencer = RootCauseInferencer()
    msgs = [_msg("Core-Router1", "down")]
    id1 = inferencer.infer(msgs, poc_engine)[0].incident_id
    id2 = inferencer.infer(msgs, poc_engine)[0].incident_id
    assert id1 != id2
    assert int(id2.split("-")[2]) == int(id1.split("-")[2]) + 1
