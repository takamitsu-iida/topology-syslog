"""ノード状態モニターの read-only HTTP API。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Query, Response
from pydantic import BaseModel

from topology_syslog.api.auth import AuthConfig, AuthMiddleware
from topology_syslog.node_monitor.models import NodeStateRecord, ProbeResult
from topology_syslog.node_monitor.scheduler import NodeMonitor


class ProbeResultOut(BaseModel):
    probe_type: str
    target: str
    success: bool | None
    observed_at: str
    latency_ms: float | None
    error: str | None


class NodeStateOut(BaseModel):
    node_id: str
    state: str
    observed_at: str
    expires_at: str
    reason: str
    probes: list[ProbeResultOut]
    monitor_id: str | None


def create_app(
    monitor: NodeMonitor,
    *,
    interval_sec: float = 30.0,
    auth_token: str | None = None,
    on_startup: Callable[[], Awaitable[None]] | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    if interval_sec <= 0:
        raise ValueError("interval_sec must be greater than zero")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        if on_startup is not None:
            await on_startup()
        task = asyncio.create_task(monitor.run_periodically(interval_sec, stop_event))
        app.state.monitor = monitor
        try:
            yield
        finally:
            stop_event.set()
            await task
            if on_shutdown is not None:
                await on_shutdown()

    app = FastAPI(title="Topology Syslog Node Monitor", version="0.1.0", lifespan=lifespan)
    app.add_middleware(AuthMiddleware, config=AuthConfig(auth_token is not None, {"reader": auth_token}))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(monitor.metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/v1/nodes/{node_id}/state", response_model=NodeStateOut)
    async def get_node_state(node_id: str) -> NodeStateOut:
        return _node_state_out(monitor.get_state(node_id))

    @app.get("/v1/nodes/states", response_model=list[NodeStateOut])
    async def get_node_states(node_id: list[str] = Query()) -> list[NodeStateOut]:
        return [_node_state_out(record) for record in monitor.get_states(node_id)]

    return app


def _node_state_out(record: NodeStateRecord) -> NodeStateOut:
    return NodeStateOut(
        node_id=record.node_id,
        state=record.state.value,
        observed_at=record.observed_at.isoformat(),
        expires_at=record.expires_at.isoformat(),
        reason=record.reason,
        probes=[_probe_out(probe) for probe in record.probes],
        monitor_id=record.monitor_id,
    )


def _probe_out(probe: ProbeResult) -> ProbeResultOut:
    return ProbeResultOut(
        probe_type=probe.probe_type,
        target=probe.target,
        success=probe.success,
        observed_at=probe.observed_at.isoformat(),
        latency_ms=probe.latency_ms,
        error=probe.error,
    )