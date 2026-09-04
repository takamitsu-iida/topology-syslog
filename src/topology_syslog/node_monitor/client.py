"""独立 node-monitor サービスの状態を読む HTTP クライアント。"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from topology_syslog.node_monitor.models import NodeState, NodeStateRecord, ProbeResult


class HttpNodeStateReader:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_sec: float = 1.0,
        auth_token: str | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_sec, headers=headers)

    def get(self, node_id: str, *, now: datetime | None = None) -> NodeStateRecord:
        observed_at = now or datetime.now(tz=timezone.utc)
        try:
            response = self._client.get(f"/v1/nodes/{node_id}/state")
            response.raise_for_status()
            return _parse_state(response.json())
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            return _unknown(node_id, observed_at, f"Node monitor unavailable: {exc}")

    def get_many(self, node_ids: list[str], *, now: datetime | None = None) -> list[NodeStateRecord]:
        observed_at = now or datetime.now(tz=timezone.utc)
        try:
            response = self._client.get("/v1/nodes/states", params=[("node_id", node_id) for node_id in node_ids])
            response.raise_for_status()
            return [_parse_state(item) for item in response.json()]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            return [_unknown(node_id, observed_at, f"Node monitor unavailable: {exc}") for node_id in node_ids]

    def close(self) -> None:
        self._client.close()


def _parse_state(data: dict) -> NodeStateRecord:
    return NodeStateRecord(
        node_id=data["node_id"],
        state=NodeState(data["state"]),
        observed_at=datetime.fromisoformat(data["observed_at"]),
        expires_at=datetime.fromisoformat(data["expires_at"]),
        reason=data.get("reason", ""),
        probes=tuple(ProbeResult(
            probe_type=probe["probe_type"],
            target=probe["target"],
            success=probe["success"],
            observed_at=datetime.fromisoformat(probe["observed_at"]),
            latency_ms=probe.get("latency_ms"),
            error=probe.get("error"),
        ) for probe in data.get("probes", [])),
        monitor_id=data.get("monitor_id"),
    )


def _unknown(node_id: str, observed_at: datetime, reason: str) -> NodeStateRecord:
    return NodeStateRecord(node_id, NodeState.UNKNOWN, observed_at, observed_at, reason)