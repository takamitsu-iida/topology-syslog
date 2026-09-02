from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from topology_syslog.api.main import _process_message_immediately, create_app
from topology_syslog.ingestion.syslog_parser import parse
from topology_syslog.knowledge.matcher import KnowledgeMatcher
from topology_syslog.knowledge.policy import SeverityAction, resolve_severity_action
from topology_syslog.knowledge.store import KnowledgeRule, KnowledgeStore
from topology_syslog.persistence.unknown_event_store import UnknownEventStore


def test_parser_normalizes_cisco_event_without_severity():
    msg = parse(b"<34>Aug 15 10:00:00 r1 %BGP-3-ADJCHANGE: neighbor down", "10.0.0.1")
    assert msg.vendor == "cisco-ios"
    assert msg.normalized_signature == "%BGP-*-ADJCHANGE"


def test_matcher_applies_only_approved_rule(tmp_path):
    (tmp_path / "rules.yaml").write_text(
        """rules:
- id: bgp-adjacency
  vendor: cisco-ios
  signature: "%BGP-*-ADJCHANGE"
  runbook: ["show ip bgp summary"]
  status: approved
  confidence: 0.9
- id: disabled-link
  signature: "%LINK-*-UPDOWN"
  status: disabled
""",
        encoding="utf-8",
    )
    matcher = KnowledgeMatcher(KnowledgeStore(tmp_path))
    known = parse(b"<34>Aug 15 10:00:00 r1 %BGP-5-ADJCHANGE: neighbor down", "10.0.0.1")
    unknown = parse(b"<34>Aug 15 10:00:00 r1 %LINK-3-UPDOWN: interface down", "10.0.0.1")

    assert matcher.classify(known).rule_id == "bgp-adjacency"
    assert known.knowledge_status == "known"
    assert known.recommended_action == "show ip bgp summary"
    assert matcher.classify(unknown) is None
    assert unknown.knowledge_status == "unknown"


def test_matcher_uses_highest_priority_matching_rule(tmp_path):
    (tmp_path / "rules.yaml").write_text(
        """rules:
- id: generic
  signature: "%BGP-*-*"
  status: approved
  priority: 1
- id: adjacency
  signature: "%BGP-*-ADJCHANGE"
  status: approved
  priority: 2
""",
        encoding="utf-8",
    )
    message = parse(b"<34>Aug 15 10:00:00 r1 %BGP-3-ADJCHANGE: neighbor down", "10.0.0.1")

    assert KnowledgeMatcher(KnowledgeStore(tmp_path)).classify(message).rule_id == "adjacency"


def test_pending_rule_is_not_applied(tmp_path):
    (tmp_path / "rules.yaml").write_text(
        "- id: pending-link\n  signature: '%LINK-*-UPDOWN'\n  status: pending\n",
        encoding="utf-8",
    )
    message = parse(b"<34>Aug 15 10:00:00 r1 %LINK-3-UPDOWN: interface down", "10.0.0.1")

    assert KnowledgeMatcher(KnowledgeStore(tmp_path)).classify(message) is None
    assert message.knowledge_status == "unknown"


def test_severity_policy_resolves_individual_and_range_actions():
    rule = KnowledgeRule(
        rule_id="policy", signature="%LINK-*-UPDOWN",
        severity_policy={"0-2": "page_immediately", "3": "create_incident", "4-5": "correlate_only", "6-7": "retain_only"},
    )

    assert resolve_severity_action(rule, 1) == SeverityAction.PAGE_IMMEDIATELY
    assert resolve_severity_action(rule, 3) == SeverityAction.CREATE_INCIDENT
    assert resolve_severity_action(rule, 4) == SeverityAction.CORRELATE_ONLY
    assert resolve_severity_action(rule, 7) == SeverityAction.RETAIN_ONLY


def test_unknown_event_store_aggregates_signature_severity_and_nodes():
    store = UnknownEventStore("sqlite:///:memory:")
    first = parse(b"<34>Aug 15 10:00:00 r1 %FOO-3-BAR: first", "10.0.0.1")
    second = parse(b"<35>Aug 15 10:00:01 r2 %FOO-4-BAR: second", "10.0.0.2")
    first.received_at = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    second.received_at = datetime(2026, 8, 15, 10, 1, tzinfo=timezone.utc)

    store.record(first)
    stored = store.record(second)

    assert stored.signature == "%FOO-*-BAR"
    assert stored.occurrence_count == 2
    assert stored.severity_counts == {"2": 1, "3": 1}
    assert stored.nodes == ["r1", "r2"]


def test_unknown_event_store_lists_newest_first():
    store = UnknownEventStore("sqlite:///:memory:")
    older = parse(b"<34>Aug 15 10:00:00 r1 %OLD-3-EVENT: old", "10.0.0.1")
    newer = parse(b"<34>Aug 15 10:01:00 r2 %NEW-3-EVENT: new", "10.0.0.2")
    older.received_at = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    newer.received_at = datetime(2026, 8, 15, 10, 1, tzinfo=timezone.utc)
    store.record(older)
    store.record(newer)

    assert [event.signature for event in store.list_events()] == ["%NEW-*-EVENT", "%OLD-*-EVENT"]


def test_ingest_classifies_and_records_unknown_events(tmp_path, poc_engine):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: known-bgp\n  signature: '%BGP-*-ADJCHANGE'\n  status: approved\n",
        encoding="utf-8",
    )
    app = create_app(
        database_url="sqlite:///:memory:",
        topology_path=str(Path(__file__).parents[2] / "poc" / "topology" / "l3_topology.json"),
        topology_source="ietf-json",
        knowledge_path=str(rules_path),
        syslog_port=0,
    )
    with TestClient(app) as client:
        response = client.post("/ingest", json={"messages": [{
            "source_ip": "10.0.0.1",
            "raw": "<34>Aug 15 10:00:00 Core-Router1 %NEW-3-EVENT: sample",
        }]})
        assert response.status_code == 200
        unknown = app.state.unknown_event_store.get("%NEW-*-EVENT")
        assert unknown is not None
        assert unknown.occurrence_count == 1
        listed = client.get("/knowledge/unknown-events")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["events"][0]["signature"] == "%NEW-*-EVENT"


def test_severity_policy_retain_only_skips_incident_creation(tmp_path, poc_engine):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: retained-link\n  signature: '%LINK-*-UPDOWN'\n  status: approved\n  severity_policy: {'0-7': retain_only}\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = poc_engine
        msg = parse(b"<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface down", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, msg))
        assert app.state.store.count() == 0


def test_severity_policy_correlate_only_updates_existing_incident(tmp_path, poc_engine):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: correlated-link\n  signature: '%LINK-*-UPDOWN'\n  status: approved\n  severity_policy: {'0-7': correlate_only}\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = poc_engine
        from topology_syslog.models import Incident
        existing = Incident(
            incident_id="INC-EXISTING", created_at=datetime.now(tz=timezone.utc),
            root_cause_node="Core-Router1", primary_event="prior", raw_log_count=1,
            raw_logs=["prior"],
        )
        app.state.store.save(existing)
        msg = parse(b"<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface down", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, msg))
        updated = app.state.store.get_by_id("INC-EXISTING")
        assert updated is not None
        assert updated.raw_log_count == 2
        assert app.state.store.count() == 1


def test_severity_policy_create_incident_creates_new_incident(tmp_path, poc_engine):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: created-link\n  signature: '%LINK-*-UPDOWN'\n  status: approved\n  severity_policy: {'0-7': create_incident}\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = poc_engine
        message = parse(b"<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface down", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, message))
        assert app.state.store.count() == 1


def test_skb_unconfigured_keeps_existing_ingest_behavior(client):
    response = client.post("/ingest", json={"messages": [{
        "source_ip": "10.0.0.1",
        "raw": "<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface down",
    }]})

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert client.get("/knowledge/unknown-events").status_code == 503


def test_sample_skb_retain_only_rule_suppresses_legacy_ignore_event(poc_engine):
    sample_path = Path(__file__).parents[2] / "configs" / "syslog_knowledge"
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(sample_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = poc_engine
        message = parse(b"<34>Aug 15 10:00:00 Core-Router1 %SYS-5-CONFIG_I: changed", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, message))
        assert message.knowledge_status == "known"
        assert app.state.store.count() == 0


def test_knowledge_review_creates_approves_and_disables_rule(tmp_path, poc_engine):
    rules_path = tmp_path / "rules.yaml"
    app = create_app(
        database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0,
    )
    with TestClient(app) as client:
        app.state.graph = poc_engine
        created = client.post("/knowledge/rules", json={
            "rule_id": "reviewed-event", "signature": "%NEW-*-EVENT",
            "runbook": ["show logging"],
        })
        assert created.status_code == 201
        assert created.json()["status"] == "pending"
        assert client.post("/knowledge/rules/reviewed-event/approve").json()["status"] == "approved"
        assert client.post("/knowledge/rules/reviewed-event/disable").json()["status"] == "disabled"


def test_knowledge_audit_tracks_rule_changes_applications_and_rollback(tmp_path, poc_engine):
    rules_path = tmp_path / "rules.yaml"
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app) as client:
        app.state.graph = poc_engine
        headers = {"X-Actor": "operator@example.test"}
        assert client.post("/knowledge/rules", headers=headers, json={
            "rule_id": "audited", "signature": "%LINK-*-UPDOWN",
        }).status_code == 201
        assert client.post("/knowledge/rules/audited/approve", headers=headers).status_code == 200
        msg = parse(b"<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: down", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, msg))
        events = client.get("/knowledge/audit", params={"rule_id": "audited"}).json()
        assert {event["event_type"] for event in events} >= {"created", "approved", "applied"}
        assert next(event for event in events if event["event_type"] == "created")["actor"] == "operator@example.test"
        assert client.post("/knowledge/rules/audited/rollback/1", headers=headers).status_code == 200
        assert client.get("/knowledge/rules").json()[0]["status"] == "pending"


def test_unknown_event_suggestions_fall_back_to_recent_incidents(tmp_path, poc_engine):
    rules_path = tmp_path / "rules.yaml"
    app = create_app(
        database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0,
    )
    with TestClient(app) as client:
        app.state.graph = poc_engine
        unknown = parse(b"<34>Aug 15 10:00:00 r1 %NEW-3-EVENT: sample", "10.0.0.1")
        app.state.unknown_event_store.record(unknown)
        from topology_syslog.models import Incident
        app.state.store.save(Incident(
            incident_id="INC-RECENT", created_at=datetime.now(tz=timezone.utc),
            root_cause_node="Core-Router1", primary_event="prior", raw_log_count=1,
        ))
        response = client.get("/knowledge/unknown-events/%25NEW-%2A-EVENT/suggestions")
        assert response.status_code == 200
        assert response.json()["source"] == "recent"
        assert response.json()["incidents"][0]["incident_id"] == "INC-RECENT"