"""pyATS を使ったネットワーク装置への SSH 接続とコマンド実行。

pyATS (unicon) は同期 API のため asyncio.to_thread() でラップして使用する。
Genie パーサーが利用可能なコマンドは構造化データ (dict) を CommandResult.parsed に格納する。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from topology_syslog.investigation.models import CommandResult
from topology_syslog.investigation.testbed_builder import TestbedBuilder

_logger = logging.getLogger(__name__)

# 許可するコマンドプレフィックス（read-only のみ）
_ALLOWED_PREFIXES = ("show ", "display ", "ping ", "traceroute ", "get ")


def _validate_command(command: str) -> None:
    """設定変更コマンドの実行を拒否するホワイトリスト検証。"""
    if not any(command.strip().lower().startswith(p) for p in _ALLOWED_PREFIXES):
        raise ValueError(
            f"許可されていないコマンドです (read-only コマンドのみ使用可): {command!r}"
        )


class DeviceConnector:
    def __init__(self, testbed_builder: TestbedBuilder, command_timeout: int = 30) -> None:
        self._builder = testbed_builder
        self._timeout = command_timeout

    def connect_and_run(
        self,
        device_id: str,
        commands: list[str],
    ) -> list[CommandResult]:
        """pyATS で装置に接続し、コマンドを順次実行して結果を返す（同期）。"""
        for cmd in commands:
            _validate_command(cmd)

        testbed = self._builder.build_for(device_id)
        device = testbed.devices[device_id]
        results: list[CommandResult] = []

        try:
            device.connect(
                init_config_commands=[],
                log_stdout=False,
                connection_timeout=self._timeout,
            )
            _logger.info("Connected to %s", device_id)

            for cmd in commands:
                ts = datetime.now(tz=timezone.utc)
                try:
                    parsed_data, output = self._execute_command(device, cmd)
                    results.append(CommandResult(
                        device_id=device_id,
                        command=cmd,
                        output=output,
                        parsed=parsed_data,
                        timestamp=ts,
                    ))
                except Exception as exc:
                    _logger.warning("コマンド失敗 [%s] %r: %s", device_id, cmd, exc)
                    results.append(CommandResult(
                        device_id=device_id,
                        command=cmd,
                        output="",
                        timestamp=ts,
                        error=str(exc),
                    ))

        except Exception as exc:
            _logger.error("接続失敗 %s: %s", device_id, exc)
            for cmd in commands:
                if not any(r.command == cmd for r in results):
                    results.append(CommandResult(
                        device_id=device_id,
                        command=cmd,
                        output="",
                        timestamp=datetime.now(tz=timezone.utc),
                        error=f"接続エラー: {exc}",
                    ))
        finally:
            try:
                device.disconnect()
            except Exception:
                pass

        return results

    def _execute_command(self, device, cmd: str) -> tuple[dict | None, str]:
        """Genie パーサーを試みる。失敗時は生テキストにフォールバック。"""
        try:
            parsed = device.parse(cmd)
            return parsed, str(parsed)
        except Exception:
            output: str = device.execute(cmd, timeout=self._timeout)
            return None, output

    async def aconnect_and_run(
        self,
        device_id: str,
        commands: list[str],
    ) -> list[CommandResult]:
        """非同期ラッパー — pyATS の同期処理を別スレッドで実行。"""
        return await asyncio.to_thread(self.connect_and_run, device_id, commands)
