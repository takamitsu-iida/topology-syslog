"""FastAPI アプリケーションファクトリー。"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from topology_syslog.api.routes.ai import router as ai_router
from topology_syslog.api.routes.incidents import router as incidents_router
from topology_syslog.api.routes.ingest import router as ingest_router
from topology_syslog.api.routes.topology import router as topology_router
from topology_syslog.api.routes.ws import ConnectionManager, router as ws_router
from topology_syslog.api.schemas import IncidentOut
from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
from topology_syslog.ingestion.syslog_filter import SyslogFilter
from topology_syslog.ingestion.syslog_receiver import start_receiver
from topology_syslog.persistence.incident_store import IncidentStore
from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader

_logger = logging.getLogger(__name__)


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


def create_app(
    database_url: str = "sqlite:///./incidents.db",
    topology_path: str | None = None,
    topology_source: str = "ietf-json",
    cors_origins: list[str] | None = None,
    ignore_file: str | None = None,
    ignore_patterns: list[str] | None = None,
    syslog_host: str = "0.0.0.0",
    syslog_port: int = 1514,
    window_sec: int = 30,
    burst_window_sec: float = 5.0,
    burst_threshold: int = 5,
    window_extend_factor: float = 2.0,
    window_sec_max: int = 120,
    inference_severity_threshold: int = 5,
    flapping_threshold: int = 3,
    ai_enabled: bool = False,
    ai_rag_path: str = ".chromadb",
    ai_cache_ttl_days: int = 7,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = IncidentStore(database_url)
        app.state.ws_manager = ConnectionManager()
        app.state.inferencer = RootCauseInferencer(
            severity_threshold=inference_severity_threshold,
            flapping_threshold=flapping_threshold,
        )
        # Syslog フィルター: デフォルトパターン + ファイル/引数パターンを合成
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
            g = (
                loader.load_from_iida_json(topology_path)
                if topology_source == "ietf-json"
                else loader.load_from_iida_yaml(topology_path)
            )
            app.state.graph = GraphEngine(g)
        else:
            app.state.graph = None

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
            buffer: list = []
            flush_task: asyncio.Task | None = None

            async def _flush_after_delay() -> None:
                nonlocal flush_task
                loop = asyncio.get_event_loop()
                start = loop.time()
                target = float(window_sec)
                extended = False

                while loop.time() - start < target:
                    remaining = target - (loop.time() - start)
                    await asyncio.sleep(min(float(burst_window_sec), remaining))
                    if not extended and _burst_detected(buffer, burst_window_sec, burst_threshold):
                        new_target = min(window_sec * window_extend_factor, float(window_sec_max))
                        if new_target > target:
                            _logger.debug("Burst detected — window extended %.0fs → %.0fs", target, new_target)
                            target = new_target
                            extended = True

                flush_task = None
                if not buffer:
                    return
                msgs = buffer.copy()
                buffer.clear()
                graph = app.state.graph
                if graph is None:
                    _logger.warning("Syslog received but topology not loaded — set TOPOLOGY_PATH")
                    return
                try:
                    incidents = app.state.inferencer.infer(msgs, graph)
                    _logger.info(
                        "Inferred %d incident(s) from %d syslog(s)",
                        len(incidents), len(msgs),
                    )
                    for inc in incidents:
                        await asyncio.to_thread(app.state.store.save, inc)
                        await app.state.ws_manager.broadcast({
                            "type": "incident.new",
                            "incident": IncidentOut.model_validate(inc).model_dump(mode="json"),
                        })
                except Exception:
                    _logger.exception("Error processing syslog messages")

            while True:
                msg = await syslog_queue.get()
                app.state.syslog_recv_count += 1
                buffer.append(msg)
                if flush_task is None:
                    flush_task = asyncio.create_task(_flush_after_delay())

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

        consumer = asyncio.create_task(_consume_syslog())
        yield
        consumer.cancel()
        if transport:
            transport.close()

    app = FastAPI(title="Topology Syslog Server", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        # 開発時は全オリジン許可; 本番では cors_origins で絞ること
        allow_origins=cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(incidents_router)
    app.include_router(topology_router)
    app.include_router(ws_router)
    app.include_router(ingest_router)
    app.include_router(ai_router)
    return app
