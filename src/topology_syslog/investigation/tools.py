"""エージェントに渡す OpenAI tool 定義とツール呼び出しのディスパッチ。"""
from __future__ import annotations

import json
import logging

from topology_syslog.investigation.device_connector import DeviceConnector
from topology_syslog.investigation.models import CommandResult
from topology_syslog.topology.graph_engine import GraphEngine

_logger = logging.getLogger(__name__)

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_topology_info",
            "description": (
                "指定デバイスのトポロジー情報（役割・隣接ノード・インターフェース一覧）を返す。"
                "どのデバイスを優先的に調査すべきか判断するために使用する。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "照会するデバイス ID（例: Spine1, Leaf2）",
                    }
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_commands",
            "description": (
                "SSH でネットワーク装置に接続し show コマンドを実行して出力を返す。"
                "read-only コマンド（show / display）のみ許可。設定変更コマンドは使用不可。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "接続先デバイス ID",
                    },
                    "commands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "実行する show コマンドのリスト",
                    },
                },
                "required": ["device_id", "commands"],
            },
        },
    },
]


class ToolDispatcher:
    def __init__(
        self,
        connector: DeviceConnector,
        graph: GraphEngine,
        topology_raw: dict,
    ) -> None:
        self._connector = connector
        self._graph = graph
        self._topology = topology_raw

    async def dispatch(self, tool_name: str, arguments: dict) -> str:
        if tool_name == "get_topology_info":
            return self._get_topology_info(arguments["device_id"])
        if tool_name == "run_commands":
            results = await self._connector.aconnect_and_run(
                arguments["device_id"],
                arguments["commands"],
            )
            return _format_results(results)
        raise ValueError(f"未知のツール: {tool_name!r}")

    def _get_topology_info(self, device_id: str) -> str:
        if not self._graph.node_exists(device_id):
            return json.dumps({"error": f"デバイス {device_id!r} はトポロジーに存在しません"})

        role = self._graph.get_node_attrs(device_id).get("role", "unknown")
        neighbors = self._graph.get_direct_neighbors(device_id)
        interfaces = self._extract_interfaces(device_id)

        return json.dumps(
            {"device_id": device_id, "role": role, "neighbors": neighbors, "interfaces": interfaces},
            ensure_ascii=False,
            indent=2,
        )

    def _extract_interfaces(self, device_id: str) -> list[dict]:
        nm = self._topology.get("network-model", {})
        for dev in nm.get("physical-layer", {}).get("device", []):
            if dev.get("device-id") == device_id:
                return [
                    {
                        "id": iface.get("interface-id"),
                        "ip": iface.get("ip-address"),
                        "description": iface.get("description"),
                    }
                    for iface in dev.get("interface", [])
                ]
        return []


def _format_results(results: list[CommandResult]) -> str:
    parts: list[str] = []
    for r in results:
        header = f"[{r.device_id}] $ {r.command}"
        body = f"ERROR: {r.error}" if r.error else r.output
        parts.append(f"{header}\n{body}")
    return "\n\n".join(parts)
