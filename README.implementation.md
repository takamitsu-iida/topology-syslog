# トポロジー駆動型シスログサーバー 実装計画

## 概要

本ドキュメントは [README.concept.md](README.concept.md) に定義された機能要件に基づき、実装を段階的に進めるための計画を記述する。

---

## 進捗ステータス凡例

| マーク | 意味 |
|---|---|
| ✅ | 完了 |
| 🔄 | 進行中 |
| ⏳ | 未着手 |

---

## 進捗サマリー

> 最終更新: 2026-08-15

| フェーズ | 状態 | 備考 |
|---|---|---|
| Phase 0: PoC | ✅ 完了 | アルゴリズム動作確認済み、YANGモデル形式へ移行済み |
| Phase 1: コアエンジン | ⏳ 未着手 | |
| Phase 2: ストレージ & API | ⏳ 未着手 | |
| Phase 3: 外部統合 | ⏳ 未着手 | |
| Phase 4: UI / ダッシュボード | ⏳ 未着手 | |
| Phase 5: 本番化 | ⏳ 未着手 | |

---

## 実装フェーズ一覧

| フェーズ | 名称 | 目的 | 主な成果物 | 状態 |
|---|---|---|---|---|
| **Phase 0** | PoC | コアアルゴリズムの動作検証 | `poc/` ディレクトリ一式 | ✅ 完了 |
| **Phase 1** | コアエンジン | 本番品質のログ受信・相関推論 | `src/topology_syslog/` パッケージ | ⏳ 未着手 |
| **Phase 2** | ストレージ & API | 永続化層とトポロジー管理API | PostgreSQL スキーマ、FastAPI サーバー | ⏳ 未着手 |
| **Phase 3** | 外部統合 | トポロジー同期・通知連携 | NETCONF/RESTCONF アダプター、Notifier | ⏳ 未着手 |
| **Phase 4** | UI / ダッシュボード | インシデント可視化 | React + Cytoscape.js フロントエンド | ⏳ 未着手 |
| **Phase 5** | 本番化 | 性能・セキュリティ・可用性 | 負荷テスト結果、本番 docker-compose | ⏳ 未着手 |

---

## ディレクトリ構造 (最終形)

```
topology-syslog/
├── README.concept.md
├── README.poc.md
├── README.implementation.md    ← 本ファイル
├── yang/                       # 既存 YANGモデル (iida-network-model)
│
├── poc/                        # Phase 0: 単機能PoC
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── topology/
│   │   └── l3_topology.json    # RFC 8345準拠 テスト用トポロジー
│   ├── src/
│   │   ├── main.py
│   │   └── requirements.txt
│   └── test_sender.py
│
├── src/                        # Phase 1+: 本番実装
│   ├── topology_syslog/        # メインパッケージ
│   │   ├── __init__.py
│   │   ├── config.py           # 設定読み込み (YAML/env)
│   │   ├── models.py           # 共通データモデル (dataclass)
│   │   │
│   │   ├── ingestion/          # 層1: ログ受信・パース
│   │   │   ├── __init__.py
│   │   │   ├── syslog_receiver.py   # UDP/TCP/TLS受信
│   │   │   └── syslog_parser.py     # RFC 3164/5424 パーサー
│   │   │
│   │   ├── topology/           # 層2a: トポロジー管理
│   │   │   ├── __init__.py
│   │   │   ├── yang_loader.py       # YANGモデル → NetworkX グラフ変換
│   │   │   ├── graph_engine.py      # グラフ操作インターフェース
│   │   │   └── sync_engine.py       # NETCONF/RESTCONF 同期 (Phase 3)
│   │   │
│   │   ├── correlation/        # 層2b: 相関・根本原因推論
│   │   │   ├── __init__.py
│   │   │   ├── time_window_buffer.py   # スライディングウィンドウ
│   │   │   └── root_cause_inferencer.py # nx.ancestors ベース推論
│   │   │
│   │   ├── persistence/        # 層3: 永続化
│   │   │   ├── __init__.py
│   │   │   ├── incident_store.py    # インシデントDB (SQLite→PostgreSQL)
│   │   │   └── raw_log_store.py     # 生ログ転送 (Loki/OpenSearch)
│   │   │
│   │   ├── notification/       # 層3: 通知
│   │   │   ├── __init__.py
│   │   │   ├── base.py              # Notifier 抽象基底クラス
│   │   │   ├── webhook.py
│   │   │   └── slack.py
│   │   │
│   │   └── api/                # REST API (FastAPI)
│   │       ├── __init__.py
│   │       ├── main.py              # アプリケーションエントリーポイント
│   │       ├── routes/
│   │       │   ├── topology.py      # トポロジー CRUD
│   │       │   └── incidents.py     # インシデント照会
│   │       └── schemas.py           # Pydantic スキーマ
│   │
│   └── tests/
│       ├── conftest.py
│       ├── test_yang_loader.py
│       ├── test_root_cause.py
│       ├── test_syslog_parser.py
│       └── test_time_window.py
│
├── frontend/                   # Phase 4: ダッシュボードUI
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── components/
│       │   ├── IncidentCard.tsx
│       │   └── TopologyMap.tsx      # Cytoscape.js ラッパー
│       └── api/
│           └── client.ts
│
└── docker/                     # Phase 5: 本番コンテナ構成
    ├── docker-compose.yml
    └── vector/
        └── vector.toml             # Vector ログコレクター設定
```

---

## Phase 0: PoC (動作原理の検証) ✅ 完了

### 目的

根本原因推論アルゴリズムが正しく機能することを、最小構成で確認する。

### 実装タスク

| # | タスク | 詳細 | 状態 |
|---|---|---|---|
| 0-1 | `poc/topology/l3_topology.json` 作成 | `Core-Router1 → Dist-Switch1 → Access-SW1` の3ノードDAGを `iida-network-model` 形式で記述 | ✅ |
| 0-2 | `poc/src/main.py` 実装 | UDP 514受信 + 10秒ウィンドウ + nx.ancestors、YANGモデル形式トポロジ読み込み対応 | ✅ |
| 0-3 | `poc/test_sender.py` 作成 | 3機器から連鎖障害ログをUDP送信するシミュレータ | ✅ |
| 0-4 | `poc/Dockerfile` & `poc/docker-compose.yml` 作成 | python:3.12-slim ベースの単一コンテナ | ✅ |
| 0-5 | PoC動作確認 | `docker compose up --build` → `test_sender.py` 実行 → 1件のインシデントに集約されることを確認 | ✅ |
| 0-6 | ノイズ混入テスト | 無関係な `Branch-Router2` からのログを混入し、2件のインシデントに正しく分離されることを確認 | ✅ |

### 完了条件

- [x] 3件の生ログが「1件の根本原因インシデント」に集約されてコンソール出力される
- [x] 関係のないログは別インシデントとして独立して出力される
- [x] トポロジーが `iida-network-model` YANG形式 (`network-model` / `physical-layer`) に準拠している

---

## Phase 1: コアエンジン ⏳ 未着手

### 目的

PoC で動作確認したロジックを、本番運用に耐えうる品質のPythonパッケージとして再実装する。

### 1-A: 共通データモデル (`models.py`)

```python
# 実装すべきデータクラス群 (設計指針)
@dataclass
class SyslogMessage:
    received_at: datetime
    source_ip: str
    hostname: str
    facility: int
    severity: int          # 0=EMERGENCY, 7=DEBUG
    message: str
    event_type: str | None  # パーサーが抽出するイベント種別

@dataclass
class Incident:
    incident_id: str        # INC-YYYYMMDD-NNN 形式
    created_at: datetime
    root_cause_node: str
    primary_event: str
    secondary_nodes: list[str]
    raw_log_count: int
    status: str             # "OPEN" | "RESOLVED"
```

### 1-B: Syslogパーサー (`ingestion/syslog_parser.py`)

- RFC 3164 (BSD Syslog) および RFC 5424 (IETF Syslog) の両方に対応
- 正規表現または `syslogmp` ライブラリを用いて以下を抽出する

| フィールド | 抽出元 |
|---|---|
| `hostname` | RFC 3164 ヘッダーの `HOSTNAME` フィールド |
| `facility` / `severity` | `<PRI>` 値から計算 (facility = PRI >> 3, severity = PRI & 7) |
| `event_type` | Cisco IOS形式 (`%FACILITY-SEVERITY-MNEMONIC`) を正規表現で抽出 |

### 1-C: Syslog受信エンジン (`ingestion/syslog_receiver.py`)

- `asyncio` ベースのUDPサーバーで実装し、高スループットを確保
- 受信したメッセージをパーサーに渡し、構造化済み `SyslogMessage` を相関エンジンのキューに投入

```python
# 設計方針
class SyslogUDPProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr): ...

async def start_receiver(host, port, queue: asyncio.Queue): ...
```

### 1-D: YANGローダー (`topology/yang_loader.py`)

- PoC では `iida-network-model` 形式のJSON（`network-model` / `physical-layer`）を使用
- 本フェーズでは同形式のYAMLファイル (`yang/examples/`) も読み込めるよう拡張する
- NetworkX の `DiGraph` に変換する際、エッジは **「上流 → 下流」の依存方向** で統一する（`role` フィールドで方向決定）

```python
class TopologyLoader:
    def load_from_iida_json(self, path: str) -> nx.DiGraph: ...
    def load_from_iida_yaml(self, path: str) -> nx.DiGraph: ...
```

### 1-E: グラフエンジン (`topology/graph_engine.py`)

```python
class GraphEngine:
    def get_ancestors(self, node_id: str) -> set[str]: ...
    def get_descendants(self, node_id: str) -> set[str]: ...
    def update_graph(self, new_graph: nx.DiGraph) -> None: ...
    def node_exists(self, node_id: str) -> bool: ...
```

### 1-F: スライディングウィンドウバッファ (`correlation/time_window_buffer.py`)

- 設定可能なウィンドウ幅 (デフォルト 30秒、設定範囲 10〜600秒)
- アラートストーム対策として最大保持件数上限 (リングバッファ) を設ける
- ウィンドウ満了時に `SyslogMessage` のリストを相関エンジンへコールバック

```python
class TimeWindowBuffer:
    def __init__(self, window_sec: int, max_size: int, on_flush: Callable): ...
    def add(self, msg: SyslogMessage) -> None: ...
    # 内部でasyncioのloop.call_later等を用いてフラッシュをスケジュール
```

### 1-G: 根本原因推論エンジン (`correlation/root_cause_inferencer.py`)

```python
class RootCauseInferencer:
    def infer(
        self,
        messages: list[SyslogMessage],
        graph: GraphEngine,
    ) -> list[Incident]: ...
```

**判定アルゴリズム (F-3.3 準拠):**

1. `logged_nodes = {m.hostname for m in messages if graph.node_exists(m.hostname)}`
2. 各ノード `n` について `ancestors = graph.get_ancestors(n)` を計算
3. `ancestors ∩ logged_nodes == ∅` なら `n` を **根本原因候補** とする
4. 根本原因候補ごとに、`logged_nodes ∩ graph.get_descendants(n)` を **二次影響ノード** として `Incident` を生成
5. いずれの根本原因にも属さないノードは **独立インシデント** として別途生成

### 1-H: 単体テスト (`tests/`)

| テストファイル | 検証内容 |
|---|---|
| `test_syslog_parser.py` | RFC 3164 / RFC 5424 フォーマット、Cisco IOS形式のパース |
| `test_yang_loader.py` | JSON/YAMLトポロジーからのグラフ構築が正しいか |
| `test_root_cause.py` | 3ノード連鎖、ノイズ混入、複数独立障害の各シナリオ |
| `test_time_window.py` | ウィンドウフラッシュのタイミング、リングバッファ上限超過 |

---

## Phase 2: ストレージ & 管理API ⏳ 未着手

### 目的

推論結果を永続化し、外部から参照・管理できるREST APIを提供する。

### 2-A: インシデントストア (`persistence/incident_store.py`)

- 開発初期は **SQLite** で実装し、後でPostgreSQLへ移行できるよう `SQLAlchemy` ORM を使用する
- テーブル設計:

```sql
CREATE TABLE incidents (
    incident_id   TEXT PRIMARY KEY,   -- INC-YYYYMMDD-NNN
    created_at    TIMESTAMP NOT NULL,
    root_cause    TEXT NOT NULL,
    primary_event TEXT NOT NULL,
    secondary_nodes JSON NOT NULL,    -- ["Dist-Switch1", "Access-SW1"]
    raw_log_count INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'OPEN'
);
```

### 2-B: FastAPI サーバー (`api/`)

提供エンドポイント:

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/incidents` | インシデント一覧 (フィルタ: status, from/to) |
| `GET` | `/incidents/{id}` | インシデント詳細 + 紐付きRawログ |
| `PUT` | `/incidents/{id}/resolve` | インシデントをRESOLVEDに更新 |
| `GET` | `/topology/nodes` | 現在のトポロジーのノード一覧 |
| `GET` | `/topology/graph` | Cytoscape.js形式でグラフを返す |
| `POST` | `/topology/reload` | YANGファイルからトポロジーを再読み込み |

### 2-C: 設定ファイル (`config.py`)

```yaml
# config.yaml (設計例)
syslog:
  listen_host: "0.0.0.0"
  listen_port: 514
  protocol: udp   # udp | tcp | tls

correlation:
  window_sec: 30
  max_buffer_size: 100000   # リングバッファ上限

topology:
  source: ietf-json   # ietf-json | iida-yaml | netconf
  path: "topology/l3_topology.json"

storage:
  database_url: "sqlite:///./incidents.db"

api:
  host: "0.0.0.0"
  port: 8080
```

---

## Phase 3: 外部統合 ⏳ 未着手

### 3-A: トポロジー自動同期 (`topology/sync_engine.py`)

- NETCONF (`ncclient`) または RESTCONF (httpx) でネットワーク機器からトポロジーを定期取得
- 取得間隔は設定可能（デフォルト: 60秒）
- トポロジー変更検知時は `GraphEngine.update_graph()` をスレッドセーフに呼び出す

```python
class TopologySyncEngine:
    def start_polling(self, interval_sec: int) -> None: ...
    def fetch_from_netconf(self, host, port, user, password) -> nx.DiGraph: ...
    def fetch_from_restconf(self, base_url: str, token: str) -> nx.DiGraph: ...
```

### 3-B: 通知システム (`notification/`)

Notifier の抽象基底クラスを定義し、各チャネルをプラグイン形式で追加できる設計とする。

```python
class BaseNotifier(ABC):
    @abstractmethod
    def send(self, incident: Incident) -> None: ...
```

| 実装クラス | 送信内容 |
|---|---|
| `WebhookNotifier` | JSON形式でPOST (汎用・ITSM連携用) |
| `SlackNotifier` | Slack Block Kit形式でポスト |

**通知ペイロード例 (Webhook):**

```json
{
  "incident_id": "INC-20260815-001",
  "root_cause": "Core-Router1",
  "primary_event": "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down",
  "secondary_affected_count": 2,
  "secondary_nodes": ["Dist-Switch1", "Access-SW1"],
  "raw_log_count": 3,
  "created_at": "2026-08-15T10:23:45Z"
}
```

---

## Phase 4: UI / ダッシュボード ⏳ 未着手

### 目的

「ログ行のタイムライン」ではなく「インシデント」を主役にした運用UIを提供する。

### 4-A: 技術選定

| 役割 | 採用技術 |
|---|---|
| フレームワーク | React + TypeScript (Vite) |
| トポロジー描画 | Cytoscape.js |
| UIコンポーネント | shadcn/ui |
| データ取得 | TanStack Query (React Query) |
| WebSocket | ネイティブ WebSocket (リアルタイム更新) |

### 4-B: 画面構成

**インシデント一覧画面 (`/incidents`)**

- アクティブなインシデントをカード形式で表示
- 各カードに「根本原因ノード」「影響範囲」「発生時刻」「RawLog件数」を表示
- OPEN/RESOLVED でフィルタリング可能

**インシデント詳細 + トポロジービュー (`/incidents/:id`)**

- Cytoscape.js でネットワーク構成図を描画
- 根本原因ノード: 赤でハイライト
- 二次影響ノード: 黄でハイライト
- 該当インシデントに紐付いたRawログをパネルに表示

### 4-C: リアルタイム更新

- バックエンド (FastAPI) から WebSocket エンドポイント (`/ws/incidents`) を提供
- 新規インシデント発生時にフロントエンドへプッシュし、画面を自動更新する

---

## Phase 5: 本番化 ⏳ 未着手

### 5-A: 高性能ログ受信 (Vector 統合)

本番環境では直接UDPを受信する代わりに **Vector** をフロントに置き、JSON変換後にアプリケーションへ転送する構成とする。

```toml
# docker/vector/vector.toml (設計例)
[sources.syslog_udp]
type = "syslog"
address = "0.0.0.0:514"
mode = "udp"

[transforms.parse_cisco]
type = "remap"
inputs = ["syslog_udp"]
source = '''
  .event_type = parse_regex(.message, r'%(?P<facility>\w+)-(?P<severity>\d)-(?P<mnemonic>\w+)') ?? null
'''

[sinks.app_http]
type = "http"
inputs = ["parse_cisco"]
uri = "http://topology-syslog-app:8080/ingest"
encoding.codec = "json"
```

### 5-B: 本番 docker-compose 構成

```
[Vector] --(JSON/HTTP)--> [topology-syslog app (FastAPI)]
                                │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
              [PostgreSQL]  [Loki]  [Notification]
                                │
                    ┌───────────┘
                    ▼
              [frontend (Nginx)]
```

### 5-C: 性能・セキュリティ要件確認

| 項目 | 目標 | 検証方法 |
|---|---|---|
| 処理スループット | 10,000 EPS | `test_sender.py` の並列送信版で負荷テスト |
| 推論遅延 | ウィンドウ時間 + 1秒以内 | 送信タイムスタンプ vs. インシデント生成タイムスタンプの差分計測 |
| メモリ使用量 | 2GB以下 (10,000ノード) | `memory_profiler` で計測 |
| TLS | Syslog-over-TLS (RFC 5425) 対応 | 自己署名証明書でE2E検証 |

---

## 実装順序のまとめ

```
Phase 0 (PoC)
    └─► Phase 1A-G (コアエンジン実装)
            └─► Phase 1H (単体テスト)
                    └─► Phase 2A-C (ストレージ & API)
                            ├─► Phase 3A (トポロジー同期)
                            ├─► Phase 3B (通知)
                            └─► Phase 4A-C (UI)
                                    └─► Phase 5A-C (本番化)
```

Phase 1 の各サブタスク (1-B〜1-G) は相互依存があるため以下の順で実装する:

```
models.py → yang_loader.py → graph_engine.py
         → syslog_parser.py → syslog_receiver.py
         → time_window_buffer.py → root_cause_inferencer.py
```

---

## 技術依存関係 (Python パッケージ)

```
# src/requirements.txt (予定)
networkx>=3.3
asyncio (stdlib)
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy>=2.0
pydantic>=2.0
httpx>=0.27          # RESTCONF同期
ncclient>=0.6        # NETCONF同期 (Phase 3)
pyyaml>=6.0
syslogmp>=0.4        # Syslogパース補助 (or 独自実装)
```
