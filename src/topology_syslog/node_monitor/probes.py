"""ノード到達性プローブ。"""
from __future__ import annotations

import asyncio
import ipaddress
import time
from datetime import datetime, timezone
from typing import Protocol

from topology_syslog.node_monitor.models import ProbeResult


class Probe(Protocol):
    async def probe(self, target: str) -> ProbeResult:
        """対象 IP アドレスを確認して結果を返す。"""


class IcmpProbe:
    def __init__(self, timeout_sec: float = 2.0) -> None:
        self._timeout_sec = timeout_sec

    async def probe(self, target: str) -> ProbeResult:
        address = _validate_ip_address(target)
        observed_at = datetime.now(tz=timezone.utc)
        started_at = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                "ping", "-n", "-c", "1", "-W", str(max(1, round(self._timeout_sec))), address,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout_sec + 1)
            return ProbeResult(
                probe_type="icmp",
                target=address,
                success=process.returncode == 0,
                observed_at=observed_at,
                latency_ms=(time.monotonic() - started_at) * 1000,
                error=None if process.returncode == 0 else stderr.decode(errors="replace").strip() or "ICMP probe failed.",
            )
        except (OSError, asyncio.TimeoutError) as exc:
            return ProbeResult(
                probe_type="icmp",
                target=address,
                success=None,
                observed_at=observed_at,
                latency_ms=(time.monotonic() - started_at) * 1000,
                error=str(exc) or type(exc).__name__,
            )


class TcpProbe:
    def __init__(self, port: int, timeout_sec: float = 2.0) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self._port = port
        self._timeout_sec = timeout_sec

    async def probe(self, target: str) -> ProbeResult:
        address = _validate_ip_address(target)
        observed_at = datetime.now(tz=timezone.utc)
        started_at = time.monotonic()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(address, self._port), timeout=self._timeout_sec
            )
            writer.close()
            await writer.wait_closed()
            return ProbeResult(
                probe_type=f"tcp/{self._port}",
                target=f"{address}:{self._port}",
                success=True,
                observed_at=observed_at,
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            return ProbeResult(
                probe_type=f"tcp/{self._port}",
                target=f"{address}:{self._port}",
                success=False,
                observed_at=observed_at,
                latency_ms=(time.monotonic() - started_at) * 1000,
                error=str(exc) or type(exc).__name__,
            )


def _validate_ip_address(target: str) -> str:
    try:
        return str(ipaddress.ip_address(target))
    except ValueError as exc:
        raise ValueError("probe target must be an IP address") from exc