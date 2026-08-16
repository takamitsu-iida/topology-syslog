"""FastAPI アプリケーションファクトリー。"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


def create_app(
    database_url: str = "sqlite:///./incidents.db",
    topology_path: str | None = None,
    topology_source: str = "ietf-json",
    cors_origins: list[str] | None = None,
    ignore_file: str | None = None,
    ignore_patterns: list[str] | None = None,
    syslog_host: str = "0.0.0.0",
    syslog_port: int = 1514,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = IncidentStore(database_url)
        app.state.ws_manager = ConnectionManager()
        app.state.inferencer = RootCauseInferencer()
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
            transport = await start_receiver(syslog_host, syslog_port, syslog_queue)
            _logger.info("Syslog UDP receiver listening on %s:%s", syslog_host, syslog_port)
        except OSError as exc:
            _logger.warning("Syslog UDP receiver could not start: %s", exc)

        async def _consume_syslog() -> None:
            while True:
                msg = await syslog_queue.get()
                app.state.syslog_recv_count += 1
                graph = app.state.graph
                if graph is None:
                    _logger.warning("Syslog received but topology not loaded — set TOPOLOGY_PATH")
                    continue
                try:
                    incidents = app.state.inferencer.infer([msg], graph)
                    _logger.info("Inferred %d incident(s) from %s", len(incidents), msg.source_ip)
                    for inc in incidents:
                        await asyncio.to_thread(app.state.store.save, inc)
                        await app.state.ws_manager.broadcast({
                            "type": "incident.new",
                            "incident": IncidentOut.model_validate(inc).model_dump(mode="json"),
                        })
                except Exception:
                    _logger.exception("Error processing syslog message")

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
    return app
