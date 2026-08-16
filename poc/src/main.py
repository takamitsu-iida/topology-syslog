"""
トポロジー駆動型シスログサーバー PoC

UDP 514 番でSYSLOGを受信し、WINDOW_TIME 秒のスライディングウィンドウで
ログをバッファリングしたのち、NetworkX を用いて根本原因ノードを自動推論する。
"""

import json
import re
import socket
import threading
import time

import networkx as nx

TOPOLOGY_FILE = "/app/topology/l3_topology.json"
WINDOW_TIME = 10  # 秒 (PoC用に短く設定)
LISTEN_PORT = 514

# Cisco IOS 形式 (%FACILITY-SEV-MNEMONIC) を抽出する正規表現
_CISCO_IOS_RE = re.compile(r"%[A-Z0-9_]+-\d+-[A-Z0-9_]+")


class CorrelatorEngine:
    def __init__(self, topo_path: str) -> None:
        self.G: nx.DiGraph = nx.DiGraph()
        self._load_topology(topo_path)
        self.buffer: list[dict] = []
        self.lock = threading.Lock()

    # ------------------------------------------------------------------
    # トポロジーロード
    # ------------------------------------------------------------------

    # デバイスロールの上流優先度 (値が小さいほど上流側)
    _ROLE_PRIORITY: dict[str, int] = {
        "border": 0,
        "spine":  0,
        "core":   1,
        "distribution": 2,
        "access": 3,
        "leaf":   3,
        "oob":    4,
        "other":  5,
    }

    def _load_topology(self, path: str) -> None:
        with open(path) as f:
            data = json.load(f)

        physical = data["network-model"]["physical-layer"]

        # デバイス一覧とロールを収集
        role_of: dict[str, int] = {}
        for dev in physical.get("device", []):
            dev_id = dev["device-id"]
            role_str = dev.get("role", "other")
            role_of[dev_id] = self._ROLE_PRIORITY.get(role_str, 5)
            self.G.add_node(dev_id)

        # 物理接続から有向エッジを生成 (上流 → 下流)
        for conn in physical.get("physical-connection", []):
            eps = conn.get("endpoint", [])
            if len(eps) != 2:
                continue
            a, b = eps[0]["device-id"], eps[1]["device-id"]
            pri_a = role_of.get(a, 5)
            pri_b = role_of.get(b, 5)
            if pri_a <= pri_b:
                self.G.add_edge(a, b)  # a が上流
            else:
                self.G.add_edge(b, a)  # b が上流

        print(f"[INIT] Topology loaded — nodes: {list(self.G.nodes)}")
        print(f"[INIT]               edges: {list(self.G.edges)}")

    # ------------------------------------------------------------------
    # ログ受信
    # ------------------------------------------------------------------

    def add_log(self, raw_data: bytes) -> None:
        try:
            text = raw_data.decode("utf-8").strip()
            # "Host:<hostname> <message>" 形式を想定
            parts = text.split(" ", 1)
            host = parts[0].removeprefix("Host:")
            msg = parts[1] if len(parts) > 1 else ""
            with self.lock:
                self.buffer.append({"host": host, "msg": msg, "time": time.time()})
            print(f"[RECV] {host} | {msg}")
        except Exception as exc:
            print(f"[ERR] Parse error: {exc}")

    # ------------------------------------------------------------------
    # ウィンドウ処理 (バックグラウンドスレッド)
    # ------------------------------------------------------------------

    def process_window(self) -> None:
        while True:
            time.sleep(WINDOW_TIME)
            with self.lock:
                if not self.buffer:
                    continue
                current_logs = list(self.buffer)
                self.buffer.clear()

            self._infer_and_print(current_logs)

    def _infer_and_print(self, logs: list[dict]) -> None:
        # トポロジーに存在するホストだけを対象にする
        logged_hosts = {log["host"] for log in logs if log["host"] in self.G}

        if not logged_hosts:
            return

        root_causes: list[str] = []
        for host in logged_hosts:
            ancestors = nx.ancestors(self.G, host)
            if not ancestors.intersection(logged_hosts):
                # 上流にログを出している親がいない → 根本原因候補
                root_causes.append(host)

        print("\n" + "=" * 60)
        print(f"[INCIDENT] Raw logs received: {len(logs)}  |  Root cause(s): {len(root_causes)}")

        for rc in root_causes:
            descendants = nx.descendants(self.G, rc)
            secondary = logged_hosts.intersection(descendants)
            primary_msg = next((l["msg"] for l in logs if l["host"] == rc), "N/A")
            event_type = self._extract_event_type(primary_msg)

            print(f"  ROOT CAUSE : {rc}")
            print(f"  EVENT      : {primary_msg}")
            if event_type:
                print(f"  EVENT TYPE : {event_type}")
            print(f"  SECONDARY  : {sorted(secondary)} ({len(secondary)} node(s))")

        # トポロジー上に存在しないホストを警告
        unknown = {log["host"] for log in logs} - set(self.G.nodes)
        if unknown:
            print(f"  WARNING    : unknown hosts (not in topology): {sorted(unknown)}")

        print("=" * 60 + "\n")

    @staticmethod
    def _extract_event_type(message: str) -> str | None:
        m = _CISCO_IOS_RE.search(message)
        return m.group() if m else None


# ------------------------------------------------------------------
# UDPサーバー
# ------------------------------------------------------------------

def start_server() -> None:
    engine = CorrelatorEngine(TOPOLOGY_FILE)

    threading.Thread(target=engine.process_window, daemon=True).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LISTEN_PORT))
    print(f"[SERVER] Syslog Receiver listening on UDP :{LISTEN_PORT} ...")
    print(f"[SERVER] Correlation window: {WINDOW_TIME} sec\n")

    while True:
        data, addr = sock.recvfrom(4096)
        engine.add_log(data)


if __name__ == "__main__":
    start_server()
