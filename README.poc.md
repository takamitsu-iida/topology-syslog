# Topology-Syslog Server PoC (概念検証) 環境構築ガイド

## 1. PoCのゴール

1. **YANGトポロジー（JSON）**を読み込み、Python(NetworkX)上にグラフを構築する。
2. 擬似的に発生させた**「同時多発SYSLOG（アラートストーム）」**を受信する。
3. 下流機器のログ（Unreachable等）を自動で集約し、**「1件の根本原因インシデント（Core-Router1の障害）」**として正しく判定・出力されることを確認する。

---

## 2. システム構成・ディレクトリ構造

```text
poc-ng-syslog/
├── docker-compose.yml
├── topology/
│   └── l3_topology.json        # RFC 8345準拠のYANGトポロジーデータ
├── src/
│   ├── main.py                 # UDP Syslog受信 & 相関エンジン (NetworkX)
│   └── requirements.txt
└── test_sender.py             # 障害発生をシミュレートするログ送信スクリプト
```

---

## 3. 構築コード & 設定ファイル

### ① `topology/l3_topology.json` (YANGトポロジーデータ)

Core-Router1 ──> Dist-Switch1 ──> Access-SW1 の階層構造を定義します。


### ② `src/requirements.txt`

```text
networkx>=3.0
```

### ③ `src/main.py` (コア処理スクリプト)

UDP 514番でログを受信し、10秒間のスライディングウィンドウで集約してNetworkXで最上流ノード（根本原因）を抽出します。

```python
import socket
import json
import time
import threading
import networkx as nx

TOPOLOGY_FILE = "/app/topology/l3_topology.json"
WINDOW_TIME = 10  # 秒 (PoC用に短く設定)

class CorrelatorEngine:
    def __init__(self, topo_path):
        self.G = nx.DiGraph()
        self.load_topology(topo_path)
        self.buffer = []
        self.lock = threading.Lock()

    def load_topology(self, path):
        with open(path, 'r') as f:
            data = json.load(f)

        networks = data.get("ietf-network:networks", {}).get("network", [])
        for net in networks:
            for node in net.get("node", []):
                child = node["node-id"]
                self.G.add_node(child)

                # supporting-node (親) からの依存関係をエッジに追加 (親 -> 子)
                for sup in node.get("ietf-network-topology:supporting-node", []):
                    parent = sup["node-ref"]
                    self.G.add_edge(parent, child)

        print(f"[INIT] Topology loaded. Nodes: {list(self.G.nodes)}, Edges: {list(self.G.edges)}")


    def add_log(self, raw_msg):
        # 簡易パース (例: "Host:Core-Router1 Msg:Link Down")
        try:
            parts = raw_msg.decode('utf-8').strip().split(" ")
            host = parts[0].replace("Host:", "")
            msg = " ".join(parts[1:])
            with self.lock:
                self.buffer.append({"host": host, "msg": msg, "time": time.time()})
            print(f"[RECV] Host: {host} | Msg: {msg}")
        except Exception as e:
            print(f"[ERR] Parse error: {e}")

    def process_window(self):
        while True:
            time.sleep(WINDOW_TIME)
            with self.lock:
                if not self.buffer:
                    continue
                current_logs = list(self.buffer)
                self.buffer.clear()

            # 発行元ホストの抽出
            logged_hosts = set(log["host"] for log in current_logs if log["host"] in self.G)

            if not logged_hosts:
                continue

            # 根本原因 (Root Cause) の判定
            root_causes = []
            for host in logged_hosts:
                # 自分より上流 (Ancestors) のノードで、今回のログに含まれているものがあるか？
                ancestors = nx.ancestors(self.G, host)
                if not ancestors.intersection(logged_hosts):
                    # 上流にログを出している親がいなければ、自分が根本原因の候補
                    root_causes.append(host)

            # 結果の構造化表示
            print("\n" + "="*50)
            print(f"🔥 [INCIDENT INFERRED] Total Raw Logs: {len(current_logs)}")
            for rc in root_causes:
                # 自身および配下の子孫ノードを特定
                descendants = nx.descendants(self.G, rc)
                impacted = logged_hosts.intersection(descendants)

                primary_log = next((l["msg"] for l in current_logs if l["host"] == rc), "N/A")

                print(f" ├─ 📍 ROOT CAUSE NODE : {rc}")
                print(f" ├─ 📝 PRIMARY EVENT   : {primary_log}")
                print(f" └─ 📉 SECONDARY AFFECTED NODES ({len(impacted)}): {list(impacted)}")
            print("="*50 + "\n")

# UDPサーバー構築
def start_server():
    engine = CorrelatorEngine(TOPOLOGY_FILE)

    # ウィンドウ処理用スレッドスタート
    threading.Thread(target=engine.process_window, daemon=True).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 514))
    print("[SERVER] Syslog Receiver listening on UDP :514...")

    while True:
        data, _ = sock.recvfrom(1024)
        engine.add_log(data)

if __name__ == "__main__":
    start_server()
```

### ④ `docker-compose.yml`

```yaml
version: '3.8'

services:
  ng-syslog:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ng-syslog-poc
    ports:
      - "514:514/udp"
    volumes:
      - ./topology:/app/topology

  # ※ Dockerfile を同ディレクトリに作成
```

> **※ `Dockerfile` (参考)**
> ```dockerfile
> FROM python:3.12-slim
> WORKDIR /app
> COPY src/requirements.txt .
> RUN pip install --no-cache-dir -r requirements.txt
> COPY src/ ./src
> CMD ["python", "src/main.py"]
> ```

---

## 4. テスト実行手順 (PoCの動かし方)

### ステップ 1: コンテナの起動
```bash
docker-compose up --build
```
*ログに `[INIT] Topology loaded...` および `Syslog Receiver listening...`
と表示されれば準備完了です。*

---

### ステップ 2: ログ送信テストスクリプトの準備・実行 (`test_sender.py`)

別の端末で以下のPythonスクリプトを実行し、**コアスイッチ障害に起因する3機器からの同時アラート**を発生させます。

```python
# test_sender.py (ホストOS側で実行)
import socket
import time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server = ("127.0.0.1", 514)

print("連鎖障害ログをUDP 514へ一括送信します...")

# 1. 最上流のコアイタがダウン
sock.sendto(b"Host:Core-Router1 %LINK-3-UPDOWN: Interface
GigabitEthernet0/0, changed state to down", server)
time.sleep(0.2)

# 2. 配下のディストリビューションスイッチがBGPダウン
sock.sendto(b"Host:Dist-Switch1 %BGP-5-ADJCHANGE: neighbor 10.0.0.1
Down", server)
time.sleep(0.2)

# 3. さらに配下のアクセススイッチが通信不能
sock.sendto(b"Host:Access-SW1 %PING-3-FAILED: Gateway 10.0.0.1
unreachable", server)

print("送信完了。コンテナ側の出力（10秒以内）を確認してください。")
```

実行コマンド:
```bash
python test_sender.py
```

---

### ステップ 3: 判定結果の確認 (期待されるログ出力)

10秒経過後、`ng-syslog` コンテナのログに以下のように**「ログは3件届いたが、根本原因（ROOT CAUSE）は
Core-Router1 の1件である」**と自動推論された出力が表示されます。

```text
[RECV] Host: Core-Router1 | Msg: %LINK-3-UPDOWN: Interface
GigabitEthernet0/0, changed state to down
[RECV] Host: Dist-Switch1 | Msg: %BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down
[RECV] Host: Access-SW1 | Msg: %PING-3-FAILED: Gateway 10.0.0.1 unreachable

==================================================
🔥 [INCIDENT INFERRED] Total Raw Logs: 3
 ├─ 📍 ROOT CAUSE NODE : Core-Router1
 ├─ 📝 PRIMARY EVENT   : %LINK-3-UPDOWN: Interface GigabitEthernet0/0,
changed state to down
 └─ 📉 SECONDARY AFFECTED NODES (2): ['Access-SW1', 'Dist-Switch1']
==================================================
```

---

## 5. 次の検証ステップ (PoCの深化)

このプロトタイプが動作したら、以下の検証を追加することで本番適用に向けた評価精度を高められます。

1. **ノイズログの混入テスト**: 関係のない別拠点のログ（例:`Host:Branch-Router2`）を同時に送信し、**「インシデントが正しく2件に分離されるか」**を確認する。
2. **CMLラボ環境テスト**: CMLの中のラボでネットワークを組み、リンクダウンやノードダウンを発生させ、**インシデントが集約されるか** を確認する。
