from datetime import datetime, timezone
import networkx as nx
from fastapi.testclient import TestClient

from topology_syslog.api.main import _process_message_immediately, create_app
from topology_syslog.ingestion.syslog_parser import parse
from topology_syslog.knowledge.classifier import EventClassifier
from topology_syslog.knowledge.matcher import KnowledgeMatcher
from topology_syslog.knowledge.policy import SeverityAction, resolve_severity_action
from topology_syslog.knowledge.store import KnowledgeRule, KnowledgeStore
from topology_syslog.models import ClassificationReason, EventAction, EventClassification, EventClassificationResult
from topology_syslog.persistence.raw_log_store import RawLogStore
from topology_syslog.persistence.unknown_event_store import UnknownEventStore
from topology_syslog.topology.graph_engine import GraphEngine


def _single_node_graph() -> GraphEngine:
    graph = nx.DiGraph()
    graph.add_node("r1", role="router")
    return GraphEngine(graph)


def _poc_like_graph() -> GraphEngine:
    graph = nx.DiGraph()
    graph.add_node("Core-Router1", role="core")
    graph.add_node("Dist-Switch1", role="distribution")
    graph.add_node("Access-SW1", role="access")
    graph.add_edge("Core-Router1", "Dist-Switch1", edge_type="physical")
    graph.add_edge("Dist-Switch1", "Access-SW1", edge_type="physical")
    return GraphEngine(graph)


def test_event_classification_model_defaults_to_unknown():
    message = parse(b"<34>Aug 15 10:00:00 r1 %FOO-3-BAR: sample", "10.0.0.1")

    assert message.event_classification == EventClassification.UNKNOWN
    assert message.event_action is None
    assert message.classification_reasons == []


def test_event_classification_result_carries_action_and_reasons():
    reason = ClassificationReason(source="skb", detail="matched approved link-down rule", confidence=0.9)
    result = EventClassificationResult(
        classification=EventClassification.FAULT_SIGNAL,
        action=EventAction.CREATE_INCIDENT,
        reasons=(reason,),
    )

    assert result.classification == EventClassification.FAULT_SIGNAL
    assert result.action == EventAction.CREATE_INCIDENT
    assert result.reasons[0].source == "skb"


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


def test_event_classifier_uses_skb_classification_and_severity_policy():
    rule = KnowledgeRule(
        rule_id="config-change",
        signature="%SYS-*-CONFIG_I",
        classification="configuration-change",
        correlation_role="informational",
        severity_policy={"0-7": "retain_only"},
        confidence=0.99,
    )
    message = parse(b"<34>Aug 15 10:00:00 r1 %SYS-5-CONFIG_I: changed", "10.0.0.1")

    result = EventClassifier().classify(message, rule)

    assert result.classification == EventClassification.CONFIG_CHANGE
    assert result.action == EventAction.RETAIN_ONLY
    assert message.event_classification == EventClassification.CONFIG_CHANGE
    assert message.event_action == EventAction.RETAIN_ONLY
    assert any(reason.source == "skb.severity_policy" for reason in message.classification_reasons)


def test_event_classifier_falls_back_to_review_for_unknown_message():
    message = parse(b"<34>Aug 15 10:00:00 r1 %NEW-3-EVENT: sample", "10.0.0.1")

    result = EventClassifier().classify(message)

    assert result.classification == EventClassification.UNKNOWN
    assert result.action == EventAction.REVIEW
    assert message.classification_reasons[0].detail == "no approved SKB rule matched"


def test_event_classifier_maps_root_cause_role_to_fault_signal():
    rule = KnowledgeRule(
        rule_id="link-down",
        signature="%LINK-*-UPDOWN",
        correlation_role="root-cause-candidate",
        severity_policy={"0-3": "create_incident"},
    )
    message = parse(b"<34>Aug 15 10:00:00 r1 %LINK-3-UPDOWN: Interface down", "10.0.0.1")

    result = EventClassifier().classify(message, rule)

    assert result.classification == EventClassification.FAULT_SIGNAL
    assert result.action == EventAction.CREATE_INCIDENT


def test_process_message_skips_non_fault_classification_for_new_incident(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: config-change\n  signature: '%SYS-*-CONFIG_I'\n  status: approved\n  classification: configuration-change\n  severity_policy: {'0-7': create_incident}\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = _single_node_graph()
        message = parse(b"<34>Aug 15 10:00:00 r1 %SYS-5-CONFIG_I: changed", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, message))

        assert message.event_classification == EventClassification.CONFIG_CHANGE
        assert message.event_action == EventAction.CREATE_INCIDENT
        assert app.state.store.count() == 0


def test_process_message_allows_fault_signal_to_create_new_incident(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: link-down\n  signature: '%LINK-*-UPDOWN'\n  status: approved\n  classification: fault-signal\n  severity_policy: {'0-7': create_incident}\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = _single_node_graph()
        message = parse(b"<34>Aug 15 10:00:00 r1 %LINK-3-UPDOWN: Interface down", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, message))

        assert message.event_classification == EventClassification.FAULT_SIGNAL
        assert message.event_action == EventAction.CREATE_INCIDENT
        assert app.state.store.count() == 1


def test_ingest_endpoint_returns_only_created_fault_signal_incidents(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """rules:
- id: config-change
  signature: "%SYS-*-CONFIG_I"
  status: approved
  classification: configuration-change
  severity_policy:
    "0-7": create_incident
- id: link-down
  signature: "%LINK-*-UPDOWN"
  status: approved
  classification: fault-signal
  severity_policy:
    "0-7": create_incident
""",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app) as client:
        app.state.graph = _single_node_graph()
        response = client.post("/ingest", json={"messages": [
            {"source_ip": "10.0.0.1", "raw": "<34>Aug 15 10:00:00 r1 %SYS-5-CONFIG_I: changed"},
            {"source_ip": "10.0.0.1", "raw": "<34>Aug 15 10:00:01 r1 %LINK-3-UPDOWN: Interface down"},
        ]})

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["root_cause_node"] == "r1"
        assert app.state.store.count() == 1


def test_raw_log_store_records_classification_metadata():
    store = RawLogStore("sqlite:///:memory:")
    message = parse(b"<34>Aug 15 10:00:00 r1 %SYS-5-CONFIG_I: changed", "10.0.0.1")
    message.knowledge_status = "known"
    message.knowledge_id = "config-change"
    message.event_classification = EventClassification.CONFIG_CHANGE
    message.event_action = EventAction.RETAIN_ONLY
    message.classification_reasons = [
        ClassificationReason(source="skb", detail="matched approved rule config-change", confidence=0.99)
    ]

    recorded = store.record(message)

    assert recorded.log_id == 1
    assert recorded.hostname == "r1"
    assert recorded.event_classification == "config-change"
    assert recorded.event_action == "retain_only"
    assert recorded.classification_reasons[0]["source"] == "skb"
    assert store.list_logs(classification="config-change")[0].knowledge_id == "config-change"


def test_ingest_endpoint_stores_non_inferred_raw_logs(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """rules:
- id: config-change
  signature: "%SYS-*-CONFIG_I"
  status: approved
  classification: configuration-change
  severity_policy:
    "0-7": retain_only
""",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app) as client:
        app.state.graph = _single_node_graph()
        response = client.post("/ingest", json={"messages": [
            {"source_ip": "10.0.0.1", "raw": "<34>Aug 15 10:00:00 r1 %SYS-5-CONFIG_I: changed"},
        ]})
        logs = client.get("/raw-logs", params={"classification": "config-change"})

        assert response.status_code == 200
        assert response.json() == []
        assert app.state.store.count() == 0
        assert logs.status_code == 200
        assert logs.json()["total"] == 1
        assert logs.json()["logs"][0]["event_action"] == "retain_only"


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


def test_unknown_event_store_records_classification_candidate_and_recommended_action():
    store = UnknownEventStore("sqlite:///:memory:")
    first = parse(b"<34>Aug 15 10:00:00 r1 %FOO-3-BAR: first", "10.0.0.1")
    second = parse(b"<35>Aug 15 10:00:01 r2 %FOO-4-BAR: second", "10.0.0.2")
    first.event_classification = EventClassification.UNKNOWN
    first.event_action = EventAction.REVIEW
    second.event_classification = EventClassification.FAULT_SIGNAL
    second.event_action = EventAction.CREATE_INCIDENT

    store.record(first)
    stored = store.record(second)

    assert stored.representative_severity == 2
    assert stored.classification_candidate == "fault-signal"
    assert stored.recommended_action == "create_incident"


def test_unknown_event_store_lists_newest_first():
    store = UnknownEventStore("sqlite:///:memory:")
    older = parse(b"<34>Aug 15 10:00:00 r1 %OLD-3-EVENT: old", "10.0.0.1")
    newer = parse(b"<34>Aug 15 10:01:00 r2 %NEW-3-EVENT: new", "10.0.0.2")
    older.received_at = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    newer.received_at = datetime(2026, 8, 15, 10, 1, tzinfo=timezone.utc)
    store.record(older)
    store.record(newer)

    assert [event.signature for event in store.list_events()] == ["%NEW-*-EVENT", "%OLD-*-EVENT"]


def test_ingest_classifies_and_records_unknown_events(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: known-bgp\n  signature: '%BGP-*-ADJCHANGE'\n  status: approved\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app) as client:
        app.state.graph = _poc_like_graph()
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


def test_unknown_event_api_includes_classification_candidate(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text("rules: []\n", encoding="utf-8")
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app) as client:
        app.state.graph = _single_node_graph()
        response = client.post("/ingest", json={"messages": [
            {"source_ip": "10.0.0.1", "raw": "<34>Aug 15 10:00:00 r1 %NEW-3-EVENT: sample"},
        ]})
        listed = client.get("/knowledge/unknown-events")

        assert response.status_code == 200
        assert listed.status_code == 200
        event = listed.json()["events"][0]
        assert event["representative_severity"] == 2
        assert event["classification_candidate"] == "unknown"
        assert event["recommended_action"] == "review"


def test_severity_policy_retain_only_skips_incident_creation(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: retained-link\n  signature: '%LINK-*-UPDOWN'\n  status: approved\n  severity_policy: {'0-7': retain_only}\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = _poc_like_graph()
        msg = parse(b"<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface down", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, msg))
        assert app.state.store.count() == 0


def test_severity_policy_correlate_only_updates_existing_incident(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: correlated-link\n  signature: '%LINK-*-UPDOWN'\n  status: approved\n  severity_policy: {'0-7': correlate_only}\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = _poc_like_graph()
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


def test_severity_policy_create_incident_creates_new_incident(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "- id: created-link\n  signature: '%LINK-*-UPDOWN'\n  status: approved\n  severity_policy: {'0-7': create_incident}\n",
        encoding="utf-8",
    )
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = _poc_like_graph()
        message = parse(b"<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface down", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, message))
        assert app.state.store.count() == 1


def test_skb_unconfigured_keeps_existing_ingest_behavior():
    app = create_app(database_url="sqlite:///:memory:", syslog_port=0)
    with TestClient(app) as client:
        app.state.graph = _poc_like_graph()
        response = client.post("/ingest", json={"messages": [{
            "source_ip": "10.0.0.1",
            "raw": "<34>Aug 15 10:00:00 Core-Router1 %LINK-3-UPDOWN: Interface down",
        }]})

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert client.get("/knowledge/unknown-events").status_code == 503


def test_sample_skb_retain_only_rule_suppresses_legacy_ignore_event():
    sample_path = "configs/syslog_knowledge"
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(sample_path), syslog_port=0)
    with TestClient(app):
        app.state.graph = _poc_like_graph()
        message = parse(b"<34>Aug 15 10:00:00 Core-Router1 %SYS-5-CONFIG_I: changed", "10.0.0.1")
        __import__("asyncio").run(_process_message_immediately(app, message))
        assert message.knowledge_status == "known"
        assert app.state.store.count() == 0


def test_knowledge_review_creates_approves_and_disables_rule(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    app = create_app(
        database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0,
    )
    with TestClient(app) as client:
        app.state.graph = _poc_like_graph()
        created = client.post("/knowledge/rules", json={
            "rule_id": "reviewed-event", "signature": "%NEW-*-EVENT",
            "runbook": ["show logging"],
        })
        assert created.status_code == 201
        assert created.json()["status"] == "pending"
        assert client.post("/knowledge/rules/reviewed-event/approve").json()["status"] == "approved"
        assert client.post("/knowledge/rules/reviewed-event/disable").json()["status"] == "disabled"


def test_knowledge_audit_tracks_rule_changes_applications_and_rollback(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    app = create_app(database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0)
    with TestClient(app) as client:
        app.state.graph = _poc_like_graph()
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


def test_unknown_event_suggestions_fall_back_to_recent_incidents(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    app = create_app(
        database_url="sqlite:///:memory:", knowledge_path=str(rules_path), syslog_port=0,
    )
    with TestClient(app) as client:
        app.state.graph = _poc_like_graph()
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