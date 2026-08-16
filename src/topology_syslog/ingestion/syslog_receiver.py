"""asyncio ベースの UDP Syslog 受信エンジン。"""
from __future__ import annotations

import asyncio
import logging

from topology_syslog.ingestion.syslog_filter import SyslogFilter
from topology_syslog.ingestion.syslog_parser import parse
from topology_syslog.models import SyslogMessage

_logger = logging.getLogger(__name__)


class SyslogUDPProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        queue: asyncio.Queue[SyslogMessage],
        syslog_filter: SyslogFilter | None = None,
    ) -> None:
        self._queue = queue
        self._filter = syslog_filter

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        msg = parse(data, addr[0])
        _logger.info("UDP syslog from %s: %s", addr[0], msg.message[:120])
        if self._filter and self._filter.is_ignored(msg):
            _logger.debug("Filtered out: %s", msg.message[:80])
            return
        self._queue.put_nowait(msg)

    def error_received(self, exc: Exception) -> None:
        _logger.warning("Syslog UDP error: %s", exc)


async def start_receiver(
    host: str,
    port: int,
    queue: asyncio.Queue[SyslogMessage],
    syslog_filter: SyslogFilter | None = None,
) -> asyncio.BaseTransport:
    """UDP リスナーを起動し、Transport を返す。"""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: SyslogUDPProtocol(queue, syslog_filter),
        local_addr=(host, port),
    )
    return transport
