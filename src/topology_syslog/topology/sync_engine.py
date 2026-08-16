"""トポロジー自動同期エンジン。

バックグラウンドスレッドで RESTCONF / NETCONF からトポロジーを定期取得し、
変化を検知したときだけ GraphEngine を更新する。
"""
from __future__ import annotations

import threading
import xml.etree.ElementTree as ET
from typing import Callable

import networkx as nx

from topology_syslog.topology.graph_engine import GraphEngine
from topology_syslog.topology.yang_loader import TopologyLoader

# NETCONF フィルター: iida-network-model の physical-layer を対象にする
_NETCONF_FILTER = """<filter>
  <network-model xmlns="urn:ietf:params:xml:ns:yang:iida-network-model"/>
</filter>"""

_YANG_NS = "urn:ietf:params:xml:ns:yang:iida-network-model"


class TopologySyncEngine:
    def __init__(
        self,
        graph: GraphEngine,
        loader: TopologyLoader | None = None,
    ) -> None:
        self._graph = graph
        self._loader = loader or TopologyLoader()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # ポーリング制御
    # ------------------------------------------------------------------

    def start_polling(
        self,
        fetch_fn: Callable[[], nx.DiGraph],
        interval_sec: int = 60,
    ) -> None:
        """バックグラウンドスレッドでポーリングを開始する。

        fetch_fn は呼び出しごとに最新の DiGraph を返す Callable。
        最初のポーリングはスレッド開始直後に即座に実行される。
        """
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Polling is already running")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(fetch_fn, interval_sec),
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """ポーリングを停止し、スレッドの終了を待つ。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _loop(self, fetch_fn: Callable[[], nx.DiGraph], interval_sec: int) -> None:
        while True:
            try:
                new_graph = fetch_fn()
                if _graph_changed(self._graph, new_graph):
                    self._graph.update_graph(new_graph)
            except Exception as exc:
                print(f"[SYNC] Topology fetch failed: {exc}", flush=True)
            if self._stop_event.wait(interval_sec):
                break  # stop() が呼ばれた

    # ------------------------------------------------------------------
    # フェッチャー実装
    # ------------------------------------------------------------------

    def fetch_from_restconf(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
    ) -> nx.DiGraph:
        """RESTCONF エンドポイントから iida-network-model JSON を取得して DiGraph を返す。"""
        import httpx
        url = f"{base_url.rstrip('/')}/restconf/data/network-model:network-model"
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return self._loader.load_from_dict(resp.json())

    def fetch_from_netconf(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        *,
        hostkey_verify: bool = False,
    ) -> nx.DiGraph:
        """NETCONF (ncclient) 経由でトポロジーを取得して DiGraph を返す。

        ncclient が未インストールの場合は ImportError を送出する。
        """
        try:
            from ncclient import manager  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "ncclient が必要です: pip install 'topology-syslog[netconf]'"
            ) from exc

        with manager.connect(
            host=host,
            port=port,
            username=user,
            password=password,
            hostkey_verify=hostkey_verify,
        ) as conn:
            reply = conn.get(filter=_NETCONF_FILTER)
            data = _xml_to_iida_dict(reply.data_xml)
            return self._loader.load_from_dict(data)


# ------------------------------------------------------------------
# モジュールレベルヘルパー (テスト可能にするため公開)
# ------------------------------------------------------------------

def _graph_changed(engine: GraphEngine, new_graph: nx.DiGraph) -> bool:
    """現在のグラフと新グラフのエッジセットを比較する。"""
    return frozenset(engine.edges) != frozenset(new_graph.edges())


def _xml_to_iida_dict(xml_str: str) -> dict:
    """NETCONF の data_xml を iida-network-model dict に変換する。"""
    root = ET.fromstring(xml_str)
    physical = root.find(f".//{{{_YANG_NS}}}physical-layer")
    if physical is None:
        return {"network-model": {"physical-layer": {"device": [], "physical-connection": []}}}

    devices = [
        {
            "device-id": dev.findtext(f"{{{_YANG_NS}}}device-id", ""),
            "role":      dev.findtext(f"{{{_YANG_NS}}}role",      "other"),
        }
        for dev in physical.findall(f"{{{_YANG_NS}}}device")
    ]

    connections = [
        {
            "endpoint": [
                {"device-id": ep.findtext(f"{{{_YANG_NS}}}device-id", "")}
                for ep in conn.findall(f"{{{_YANG_NS}}}endpoint")
            ]
        }
        for conn in physical.findall(f"{{{_YANG_NS}}}physical-connection")
    ]

    return {
        "network-model": {
            "physical-layer": {
                "device": devices,
                "physical-connection": connections,
            }
        }
    }
