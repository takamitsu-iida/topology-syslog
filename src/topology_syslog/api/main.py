"""FastAPI アプリケーションファクトリー。"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from topology_syslog.api.auth import AuthConfig, AuthMiddleware, validate_cors_origins
from topology_syslog.api.routes.ai import router as ai_router
from topology_syslog.maintenance.checker import MaintenanceChecker
from topology_syslog.api.routes.filter import router as filter_router
from topology_syslog.api.routes.incidents import router as incidents_router
from topology_syslog.api.routes.ingest import router as ingest_router
from topology_syslog.api.routes.investigation import router as investigation_router
from topology_syslog.api.routes.knowledge import router as knowledge_router
from topology_syslog.api.routes.node_states import router as node_states_router
from topology_syslog.api.routes.node_state_events import router as node_state_events_router
from topology_syslog.api.routes.raw_logs import router as raw_logs_router
from topology_syslog.api.routes.topology import router as topology_router
from topology_syslog.api.routes.ws import ConnectionManager, router as ws_router
from topology_syslog.api.schemas import IncidentOut
from topology_syslog.correlation.incident_lifecycle import IncidentLifecycle
from topology_syslog.correlation.incident_merger import IncidentMerger, MergeAction
from topology_syslog.correlation.recovery_matcher import RecoveryMatcher
from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
from topology_syslog.ingestion.syslog_filter import SyslogFilter
from topology_syslog.ingestion.syslog_receiver import start_receiver
from topology_syslog.knowledge.classifier import EventClassifier, can_create_new_incident, should_skip_inference
from topology_syslog.notification.base import NotificationEvent
from topology_syslog.persistence.incident_store import IncidentStore
from topology_syslog.persistence.investigation_store import InvestigationStore
from topology_syslog.persistence.knowledge_audit_store import KnowledgeAuditStore
from topology_syslog.persistence.raw_log_store import RawLogStore
from topology_syslog.persistence.unknown_event_store import UnknownEventStore
from topology_syslog.persistence.node_state_event_store import NodeStateEventStore
from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader, device_severity_map

_logger = logging.getLogger(__name__)


_ROUTING_PREFIXES = ("%BGP-", "%OSPF-", "%ISIS-", "%EIGRP-", "%RIP-")


def _burst_detected(
    buffer: list,
    burst_window_sec: float,
    burst_threshold: int,
) -> bool:
    """直近 burst_window_sec 秒以内に burst_threshold 件以上のメッセージがあるか。"""
    if burst_threshold <= 0 or burst_window_sec <= 0:
        return False
    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=burst_window_sec)
    return sum(1 for m in buffer if m.received_at >= cutoff) >= burst_threshold


def _has_routing_events(buffer: list) -> bool:
    """BGP/OSPF 等ルーティングイベントがバッファに含まれるか。"""
    return any(
        any(p in m.message for p in _ROUTING_PREFIXES)
        for m in buffer
    )


async def _process_message_immediately(app: FastAPI, msg) -> list:
    if app.state.syslog_filter.is_ignored(msg):
        return []

    matcher = app.state.knowledge_matcher
    rule = None
    if matcher is not None:
        rule = matcher.classify(msg)

    classification_enforced = matcher is not None
    classification_result = app.state.event_classifier.classify(msg, rule)
    if matcher is not None and msg.knowledge_status == "unknown":
        await asyncio.to_thread(app.state.unknown_event_store.record, msg)
    await asyncio.to_thread(app.state.raw_log_store.record, msg)
    if should_skip_inference(classification_result):
        _logger.debug("Retaining SYSLOG without inference: signature=%s", msg.normalized_signature)
        return []

    graph = app.state.graph
    if graph is None:
        _logger.warning("Syslog received but topology not loaded — set TOPOLOGY_PATH")
        return []

    if msg.is_recovery:
        if not graph.node_exists(msg.hostname):
            return []
        open_incidents = await asyncio.to_thread(app.state.store.list_open_lifecycle)
        matches = app.state.recovery_matcher.find_matches(msg, open_incidents)
        updated_ids: set[str] = set()
        for incident in open_incidents:
            incident_matches = [match for match in matches if match.incident.incident_id == incident.incident_id]
            if not incident_matches:
                continue
            updated = app.state.lifecycle.apply_recovery(incident, incident_matches, msg.received_at)
            if await asyncio.to_thread(app.state.store.update, updated):
                updated_ids.add(updated.incident_id)
                await _notify_lifecycle(app, updated, NotificationEvent.RECOVERING)
                await app.state.ws_manager.broadcast({
                    "type": "incident.recovering",
                    "incident_id": updated.incident_id,
                    "incident": IncidentOut.model_validate(updated).model_dump(mode="json"),
                })
                _schedule_recovery_confirmation(app, updated.incident_id, msg.received_at)
        if app.state.vigil_notifier is not None:
            try:
                await asyncio.to_thread(app.state.vigil_notifier.resolve_by_source, msg.hostname)
            except Exception:
                _logger.warning("Failed to resolve vigil incidents for node %s", msg.hostname)
        if not updated_ids:
            _logger.debug("Recovery SYSLOG did not match any open incident: node=%s signature=%s", msg.hostname, msg.normalized_signature)
        return [
            incident for incident in open_incidents
            if incident.incident_id in updated_ids
        ]

    if app.state.maintenance_checker is not None:
        app.state.maintenance_checker.reload_if_changed()

    try:
        incidents = app.state.inferencer.infer([msg], graph)
    except Exception:
        _logger.exception("Error inferring incident from single syslog message")
        return []

    if not incidents:
        return []

    open_incidents = await asyncio.to_thread(app.state.store.list_open_lifecycle)
    affected_incidents = []
    for inc in incidents:
        if app.state.maintenance_checker is not None:
            plan = app.state.maintenance_checker.find_active_plan(inc, at=msg.received_at, graph=graph)
            if plan is not None:
                inc.status = "CLOSED"
                inc.maintenance_plan_id = plan.plan_id
                _logger.info(
                    "Auto-closed %s (root_cause=%s): matches maintenance plan %s '%s'",
                    inc.incident_id, inc.root_cause_node,
                    plan.plan_id, plan.title,
                )

        inc.recurrence_count = await asyncio.to_thread(app.state.store.count_by_root_cause, inc.root_cause_node)
        decision = app.state.merger.find_merge_target(inc, open_incidents, graph)

        if decision.action == MergeAction.NEW:
            if not can_create_new_incident(classification_result, enforce=classification_enforced):
                _logger.debug(
                    "Suppressing new incident for non-fault SYSLOG: signature=%s classification=%s action=%s",
                    msg.normalized_signature,
                    classification_result.classification.value,
                    classification_result.action.value if classification_result.action else None,
                )
                continue
            await asyncio.to_thread(app.state.store.save, inc)
            if app.state.vigil_notifier is not None:
                try:
                    await asyncio.to_thread(app.state.vigil_notifier.send, inc)
                except Exception:
                    _logger.warning("Failed to forward incident %s to vigil", inc.incident_id, exc_info=True)
            await app.state.ws_manager.broadcast({
                "type": "incident.new",
                "incident": IncidentOut.model_validate(inc).model_dump(mode="json"),
            })
            open_incidents.append(inc)
            affected_incidents.append(inc)
            continue

        target = decision.target
        if target is None:
            await asyncio.to_thread(app.state.store.save, inc)
            affected_incidents.append(inc)
            continue

        merged = app.state.merger.merge(target, inc, graph)
        merged = app.state.lifecycle.apply_fault(merged, msg, flap_threshold=app.state.recovery_flap_threshold)
        merged.recurrence_count = inc.recurrence_count
        if await asyncio.to_thread(app.state.store.update, merged):
            event = NotificationEvent.FLAPPING if merged.condition == "FLAPPING" else NotificationEvent.UPDATED
            await _notify_lifecycle(app, merged, event)
            await app.state.ws_manager.broadcast({
                "type": "incident.updated",
                "incident": IncidentOut.model_validate(merged).model_dump(mode="json"),
            })
        else:
            await asyncio.to_thread(app.state.store.save, merged)

        for idx, existing in enumerate(open_incidents):
            if existing.incident_id == target.incident_id:
                open_incidents[idx] = merged
                break
        affected_incidents.append(merged)

    return affected_incidents


def _schedule_recovery_confirmation(app: FastAPI, incident_id: str, recovery_seen_at: datetime) -> None:
    task = app.state.recovery_tasks.pop(incident_id, None)
    if task is not None:
        task.cancel()
    task = asyncio.create_task(_confirm_recovery_after_quiet_period(app, incident_id, recovery_seen_at))
    app.state.recovery_tasks[incident_id] = task


async def _confirm_recovery_after_quiet_period(app: FastAPI, incident_id: str, recovery_seen_at: datetime) -> None:
    try:
        await asyncio.sleep(app.state.recovery_quiet_period_sec)
        incident = await asyncio.to_thread(app.state.store.get_by_id, incident_id)
        if incident is None or incident.status != "OPEN" or incident.condition != "RECOVERING":
            return
        if incident.last_fault_at is not None and incident.last_fault_at > recovery_seen_at:
            return
        recovered = app.state.lifecycle.mark_recovered(incident, datetime.now(tz=timezone.utc))
        if await asyncio.to_thread(app.state.store.update, recovered):
            await _notify_lifecycle(app, recovered, NotificationEvent.RECOVERED)
            await app.state.ws_manager.broadcast({
                "type": "incident.recovered",
                "incident_id": recovered.incident_id,
                "incident": IncidentOut.model_validate(recovered).model_dump(mode="json"),
            })
    except asyncio.CancelledError:
        raise
    except Exception:
        _logger.exception("Error confirming recovered incident %s", incident_id)
    finally:
        current = app.state.recovery_tasks.get(incident_id)
        if current is asyncio.current_task():
            app.state.recovery_tasks.pop(incident_id, None)


async def _notify_lifecycle(app: FastAPI, incident, event: NotificationEvent) -> None:
    if app.state.vigil_notifier is None:
        return
    try:
        await asyncio.to_thread(app.state.vigil_notifier.send_lifecycle, incident, event)
    except Exception:
        _logger.warning("Failed to forward lifecycle event %s for incident %s", event.value, incident.incident_id, exc_info=True)


def create_app(
    database_url: str = "sqlite:///./incidents.db",
    topology_path: str | None = None,
    topology_source: str = "ietf-json",
    cors_origins: list[str] | None = None,
    ignore_file: str | None = None,
    ignore_patterns: list[str] | None = None,
    syslog_host: str = "0.0.0.0",
    syslog_port: int = 1514,
    correlation_mode: str = "immediate",
    window_sec: int = 30,
    burst_window_sec: float = 5.0,
    burst_threshold: int = 3,
    window_extend_factor: float = 2.0,
    window_sec_max: int = 120,
    inference_severity_threshold: int = 5,
    flapping_threshold: int = 3,
    recovery_quiet_period_sec: float = 30.0,
    recovery_flap_threshold: int = 2,
    ai_enabled: bool = False,
    ai_rag_path: str = ".chromadb",
    ai_cache_ttl_days: int = 7,
    vigil_url: str | None = None,
    vigil_team_name: str = "default",
    investigation_enabled: bool = False,
    investigation_testbed_file: str | None = None,
    investigation_max_turns: int = 8,
    investigation_command_timeout: int = 30,
    maintenance_dir: str | None = None,
    knowledge_path: str | None = None,
    auth_enabled: bool = False,
    auth_reader_token: str | None = None,
    auth_operator_token: str | None = None,
    auth_admin_token: str | None = None,
    node_monitor_url: str | None = None,
    node_monitor_token: str | None = None,
    node_monitor_event_token: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = IncidentStore(database_url)
        app.state.investigation_store = InvestigationStore(database_url)
        interrupted = await asyncio.to_thread(app.state.investigation_store.mark_running_as_interrupted)
        if interrupted:
            _logger.warning("Marked %d interrupted investigation(s) after restart", interrupted)
        app.state.raw_log_store = RawLogStore(database_url)
        app.state.knowledge_matcher = None
        app.state.unknown_event_store = None
        app.state.knowledge_audit_store = None
        if knowledge_path:
            from topology_syslog.knowledge.matcher import KnowledgeMatcher
            from topology_syslog.knowledge.store import KnowledgeStore

            app.state.knowledge_audit_store = KnowledgeAuditStore(database_url)
            app.state.knowledge_matcher = KnowledgeMatcher(
                KnowledgeStore(knowledge_path), app.state.knowledge_audit_store
            )
            app.state.unknown_event_store = UnknownEventStore(database_url)
            _logger.info("SYSLOG Knowledge Base loaded from %s", knowledge_path)
        app.state.ws_manager = ConnectionManager()
        app.state.correlation_mode = correlation_mode
        app.state.merger = IncidentMerger()
        app.state.lifecycle = IncidentLifecycle()
        app.state.recovery_matcher = RecoveryMatcher()
        app.state.recovery_quiet_period_sec = recovery_quiet_period_sec
        app.state.recovery_flap_threshold = recovery_flap_threshold
        app.state.recovery_tasks = {}
        app.state.event_classifier = EventClassifier()
        app.state.maintenance_checker = (
            MaintenanceChecker(maintenance_dir) if maintenance_dir else None
        )
        if vigil_url:
            from topology_syslog.notification.vigil import VigilNotifier
            app.state.vigil_notifier = VigilNotifier(vigil_url, team_name=vigil_team_name)
        else:
            app.state.vigil_notifier = None
        app.state.node_state_reader = None
        app.state.node_monitor_event_token = node_monitor_event_token
        app.state.node_state_event_store = NodeStateEventStore(database_url)
        if node_monitor_url:
            from topology_syslog.node_monitor.client import HttpNodeStateReader
            app.state.node_state_reader = HttpNodeStateReader(node_monitor_url, auth_token=node_monitor_token)
        app.state.inferencer = RootCauseInferencer(
            severity_threshold=inference_severity_threshold,
            flapping_threshold=flapping_threshold,
            node_state_reader=app.state.node_state_reader,
        )
        # Syslog フィルター: デフォルトパターン + ファイル/引数パターンを合成
        app.state.ignore_file = ignore_file
        extra: list[str] = list(ignore_patterns or [])
        if ignore_file:
            app.state.syslog_filter = SyslogFilter(
                SyslogFilter.from_file(ignore_file).patterns + extra
            )
        else:
            app.state.syslog_filter = SyslogFilter(extra)
        app.state.topology_path = topology_path
        app.state.topology_source = topology_source
        if topology_path:
            loader = TopologyLoader()
            if topology_source == "ietf-json":
                with open(topology_path) as f:
                    topology_raw: dict = json.load(f)
            else:
                with open(topology_path) as f:
                    topology_raw = yaml.safe_load(f)
            g = loader.load_from_dict(topology_raw)
            app.state.graph = GraphEngine(g)
            app.state.topology_raw = topology_raw
            app.state.syslog_filter.update_device_severity(device_severity_map(g))
        else:
            app.state.graph = None
            app.state.topology_raw = {}

        # UDP syslog 受信エンジンを起動（rsyslog が 514 を使うため 1514 等の非特権ポートを使う）
        syslog_queue: asyncio.Queue = asyncio.Queue()
        app.state.syslog_recv_count = 0
        app.state.syslog_port = syslog_port
        transport = None
        try:
            transport = await start_receiver(
                syslog_host, syslog_port, syslog_queue, app.state.syslog_filter
            )
            _logger.info("Syslog UDP receiver listening on %s:%s", syslog_host, syslog_port)
        except OSError as exc:
            _logger.warning("Syslog UDP receiver could not start: %s", exc)

        async def _consume_syslog() -> None:
            while True:
                msg = await syslog_queue.get()
                app.state.syslog_recv_count += 1
                await _process_message_immediately(app, msg)

        # AI コンポーネント（オプション）— chromadb / openai が未インストールでも起動可能
        app.state.report_generator = None
        app.state.rag_store = None
        if ai_enabled:
            from topology_syslog.ai.llm_client import create_llm_client
            from topology_syslog.ai.query_cache import QueryCache
            from topology_syslog.ai.rag_store import RAGStore
            from topology_syslog.ai.report_generator import ReportGenerator

            llm   = create_llm_client()
            cache = QueryCache(database_url, ttl_days=ai_cache_ttl_days)
            rag   = RAGStore(ai_rag_path)
            app.state.rag_store = rag
            app.state.report_generator = ReportGenerator(llm, cache, rag)
            _logger.info("AI report generator ready (rag_path=%s)", ai_rag_path)

        # 調査エージェント（オプション）— pyats / genie と testbed YAML が必要
        app.state.investigation_agent = None
        if investigation_enabled:
            from topology_syslog.ai.llm_client import create_llm_client
            from topology_syslog.investigation.agent import InvestigationAgent
            from topology_syslog.investigation.device_connector import DeviceConnector
            from topology_syslog.investigation.testbed_builder import TestbedBuilder
            from topology_syslog.investigation.tools import ToolDispatcher

            if not investigation_testbed_file:
                raise ValueError(
                    "INVESTIGATION_ENABLED=true の場合は PYATS_TESTBED_FILE の指定が必要です"
                )
            testbed_builder = TestbedBuilder(investigation_testbed_file)
            connector = DeviceConnector(testbed_builder, command_timeout=investigation_command_timeout)
            dispatcher = ToolDispatcher(connector, app.state.graph, app.state.topology_raw)
            inv_llm = create_llm_client()
            app.state.investigation_agent = InvestigationAgent(dispatcher, inv_llm)
            _logger.info(
                "Investigation agent ready (max_turns=%d, devices=%s)",
                investigation_max_turns,
                testbed_builder.known_devices,
            )

        async def _run_cleanup() -> None:
            while True:
                await asyncio.sleep(24 * 3600)
                try:
                    purged = await asyncio.to_thread(app.state.store.purge_old_closed, 90)
                    if purged:
                        _logger.info("Cleanup: purged %d old CLOSED incidents (>90 days)", purged)
                    if app.state.report_generator is not None:
                        purged_c = await asyncio.to_thread(app.state.report_generator.purge_cache)
                        if purged_c:
                            _logger.info("Cleanup: purged %d expired AI cache entries", purged_c)
                except Exception:
                    _logger.exception("Cleanup task error")

        consumer = asyncio.create_task(_consume_syslog())
        cleanup = asyncio.create_task(_run_cleanup())
        yield
        consumer.cancel()
        cleanup.cancel()
        for task in app.state.recovery_tasks.values():
            task.cancel()
        close_node_state_reader = getattr(app.state.node_state_reader, "close", None)
        if close_node_state_reader is not None:
            close_node_state_reader()
        if transport:
            transport.close()

    auth_config = AuthConfig(auth_enabled, {
        "reader": auth_reader_token,
        "operator": auth_operator_token,
        "admin": auth_admin_token,
    })
    app = FastAPI(title="Topology Syslog Server", version="0.1.0", lifespan=lifespan)
    cors_origins = validate_cors_origins(auth_enabled, cors_origins)
    app.add_middleware(
        AuthMiddleware,
        config=auth_config,
    )
    app.add_middleware(
        CORSMiddleware,
        # 開発時は全オリジン許可; 本番では cors_origins で絞ること
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(incidents_router)
    app.include_router(topology_router)
    app.include_router(filter_router)
    app.include_router(ws_router)
    app.include_router(raw_logs_router)
    app.include_router(ingest_router)
    app.include_router(ai_router)
    app.include_router(investigation_router)
    app.include_router(knowledge_router)
    app.include_router(node_states_router)
    app.include_router(node_state_events_router)
    return app
