"""FastAPI アプリケーションファクトリー。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from topology_syslog.api.routes.incidents import router as incidents_router
from topology_syslog.api.routes.ingest import router as ingest_router
from topology_syslog.api.routes.topology import router as topology_router
from topology_syslog.api.routes.ws import ConnectionManager, router as ws_router
from topology_syslog.correlation.root_cause_inferencer import RootCauseInferencer
from topology_syslog.ingestion.syslog_filter import SyslogFilter
from topology_syslog.persistence.incident_store import IncidentStore
from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader


def create_app(
    database_url: str = "sqlite:///./incidents.db",
    topology_path: str | None = None,
    topology_source: str = "ietf-json",
    cors_origins: list[str] | None = None,
    ignore_file: str | None = None,
    ignore_patterns: list[str] | None = None,
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
        yield

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
