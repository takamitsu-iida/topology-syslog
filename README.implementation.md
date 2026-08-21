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

> 最終更新: 2026-08-20

| フェーズ | 状態 | 備考 |
|---|---|---|
| Phase 0: PoC | ✅ 完了 | アルゴリズム動作確認済み、YANGモデル形式へ移行済み |
| Phase 1: コアエンジン | ✅ 完了 | 29 tests passed |
| Phase 2: ストレージ & API | ✅ 完了 | 53 tests passed (累計) |
| Phase 3: 外部統合 | ✅ 完了 | 72 tests passed (累計) |
| Phase 4: UI / ダッシュボード | ✅ 完了 | 80 tests passed (累計) |
| Phase 5: 本番化 | ⏳ 未着手 | |
| Phase 6: BGPピアリングのグラフエッジ化 | ✅ 完了 | 109 tests passed (累計) |
| Phase 7: AI 障害レポート | ✅ 完了 | OpenAI/Ollama 対応、RAG+キャッシュ、UI統合 |
| Phase 8: 推論エンジン強化 | ✅ 完了 | 127 tests passed (累計) |
| Phase 9: 装置調査エージェント | ✅ 完了 | pyATS + LLM ReAct ループ |

---

## 実装フェーズ一覧

| フェーズ | 名称 | 目的 | 主な成果物 | 状態 |
|---|---|---|---|---|
| **Phase 0** | PoC | コアアルゴリズムの動作検証 | `poc/` ディレクトリ一式 | ✅ 完了 |
| **Phase 1** | コアエンジン | 本番品質のログ受信・相関推論 | `src/topology_syslog/` パッケージ | ✅ 完了 |
| **Phase 2** | ストレージ & API | 永続化層とトポロジー管理API | PostgreSQL スキーマ、FastAPI サーバー | ✅ 完了 |
| **Phase 3** | 外部統合 | トポロジー同期・通知連携 | NETCONF/RESTCONF アダプター、Notifier | ✅ 完了 |
| **Phase 4** | UI / ダッシュボード | インシデント可視化 | React + Cytoscape.js フロントエンド | ✅ 完了 |
| **Phase 5** | 本番化 | 性能・セキュリティ・可用性 | 負荷テスト結果、本番 docker-compose | ⏳ 未着手 |
| **Phase 6** | BGPピアリングのグラフエッジ化 | iBGP等でトポロジーと一致しないピアもインシデント集約対象にする | `yang_topology.yaml`, `yang_loader.py`, `graph_engine.py`, フロントエンド | ✅ 完了 |
| **Phase 7** | AI 障害レポート | LLM による障害分析レポート自動生成（RAG + クエリキャッシュ） | `ai/` モジュール、`/incidents/{id}/report` API、UI ボタン | ✅ 完了 |
| **Phase 8** | 推論エンジン強化 | 集約精度・カバレッジ・応答速度を段階的に改善 | `root_cause_inferencer.py`, `graph_engine.py` | ✅ 完了 |
| **Phase 9** | 装置調査エージェント | インシデント発生時に実機へ SSH 接続して情報収集。どの装置にどのコマンドを実行するかを LLM が自律判断する ReAct エージェント | `investigation/` モジュール、`/incidents/{id}/investigation` API | ✅ 完了 |

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

## Phase 1: コアエンジン ✅ 完了

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

## Phase 2: ストレージ & 管理API ✅ 完了

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

## Phase 3: 外部統合 ✅ 完了

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

## Phase 4: UI / ダッシュボード ✅ 完了

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


### 起動方法

バックエンド

```bash
uv sync
direnv allow
topology-syslog
```

フロントエンド (別ターミナル)

```bash
cd frontend && npm install && npm run dev
```

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

---

## 2026-08-16 実施内容（バグ修正・機能追加）

| # | 内容 | 対象ファイル |
|---|---|---|
| 1 | `SyslogMessage.raw_message` → `message` 属性名修正 | `ingestion/syslog_receiver.py` |
| 2 | アプリケーションロガー未初期化でINFOログが出ない問題を修正 | `__main__.py` |
| 3 | RFC 3164パーサーでhostnameがIPアドレスの場合、メッセージ本文の `<seq>: <hostname>:` からノード名を抽出するよう修正 | `ingestion/syslog_parser.py` |
| 4 | `_consume_syslog()` が1メッセージずつ `infer()` を呼んでいたため、タイムウィンドウバッファを組み込みに修正（`WINDOW_SEC` 環境変数で制御） | `api/main.py`, `__main__.py` |
| 5 | `Incident` モデルに `raw_logs: list[str]` を追加し、元SYSLOGをインシデント詳細画面で確認できるようにした | `models.py`, `root_cause_inferencer.py`, `incident_store.py`, `schemas.py`, `types.ts`, `IncidentDetail.tsx` |

---

## Phase 6: BGPピアリングのグラフエッジ化 ⏳ 未着手

### 目的

iBGPフルメッシュやRouteReflector構成など、物理的に隣接しないノード間のBGPピアリングをグラフエッジとして定義し、BGPセッション障害も根本原因推論の対象にする。

### 背景

現状の推論エンジンは `ancestor/descendant` 関係（物理エッジ由来）でのみ集約を行う。iBGP Leaf-Leaf のように物理エッジがないノード間でBGPセッションが切れた場合、それぞれが独立したインシデントとして生成されてしまう。

### 実装タスク

| # | タスク | 対象ファイル | 状態 |
|---|---|---|---|
| 6-1 | `yang_topology.yaml` に `routing-layer.bgp-session` セクションを追加 | `configs/clos/yang_topology.yaml` | ⏳ |
| 6-2 | `yang_loader.py` でBGPセッションをエッジとして読み込む | `topology/yang_loader.py` | ⏳ |
| 6-3 | `graph_engine.py` に `edges_with_data()` メソッドを追加 | `topology/graph_engine.py` | ⏳ |
| 6-4 | フロントエンドのトポロジービューでBGPエッジを破線で表示 | `components/TopologyMap.tsx`, `api/routes/topology.py` | ⏳ |

### YAMLスキーマ（設計）

```yaml
network-model:
  physical-layer:
    device: [...]
    physical-connection: [...]
  routing-layer:                    # ← 追加
    bgp-session:
      - session-id: "Leaf1-Leaf2-iBGP"
        type: ibgp                  # ibgp | ebgp
        endpoint:
          - device-id: "Leaf1"
          - device-id: "Leaf2"
      - session-id: "Spine1-Leaf1-eBGP"
        type: ebgp
        endpoint:
          - device-id: "Spine1"
          - device-id: "Leaf1"
```

### エッジ方向の決定ルール

| BGP種別 | 方向決定ルール |
|---|---|
| eBGP | role優先度（既存の物理エッジと同じ） |
| iBGP（同一ロール） | `device-id` のアルファベット順で固定（循環グラフ回避） |

### 集約後の動作イメージ

```
# BGPエッジ追加後: Leaf1 → Leaf2（iBGP, アルファベット順）

logged_nodes = {Leaf1, Leaf2}  # iBGPセッション切断のみ
Leaf1 の ancestors → {}        # 根本原因
Leaf1 の descendants → {Leaf2} # BGPエッジ経由
→ 1件のインシデント（Leaf1が根本原因、Leaf2が二次影響）
```

### 完了条件

- [ ] `yang_topology.yaml` の `bgp-session` を読み込んでグラフエッジが追加される
- [ ] iBGP Leaf-Leaf の両ノードからSYSLOGが来た場合に1件のインシデントに集約される
- [ ] フロントエンドのトポロジービューでBGPエッジが破線表示される
- [ ] 既存の物理エッジ由来の集約が壊れていないこと（既存テストがパスすること）

---

## Phase 7: AI 障害レポート ✅ 完了

### 目的

インシデントに対して LLM（OpenAI / Ollama）を使い障害分析レポートを自動生成する。
同種の障害は再問い合わせせずキャッシュから返し、過去インシデントを RAG として蓄積することで精度を継続的に向上させる。

### アーキテクチャ

```
インシデント詳細 UI
        │ POST /incidents/{id}/report
        ▼
ReportGenerator.generate(incident)
        │
        ├─ QueryCache.get(fingerprint)  ─── HIT → キャッシュ済みレポートを即返却
        │                                   MISS ↓
        ├─ RAGStore.search_similar()        過去の類似インシデントを ChromaDB で検索
        │
        ├─ LLMClient.ask(prompt)            OpenAI または Ollama へ問い合わせ
        │
        ├─ QueryCache.set(fingerprint, report)
        └─ RAGStore.add(incident)
```

**キャッシュキー（フィンガープリント）**: `root_cause_node` + Cisco IOS イベント種別（`%FAC-SEV-MNEM`）+ `secondary_nodes` の SHA-256。
同じノードで同じ種別の障害が再発した場合、LLM への問い合わせをスキップする。

### 実装タスク

| # | タスク | 対象ファイル | 状態 |
|---|---|---|---|
| 7-1 | `ai/llm_client.py` — OpenAI / Ollama 抽象クライアント | `ai/llm_client.py` | ✅ |
| 7-2 | `ai/query_cache.py` — SQLite キャッシュ（TTL 付き） | `ai/query_cache.py` | ✅ |
| 7-3 | `ai/rag_store.py` — ChromaDB セマンティック類似検索 | `ai/rag_store.py` | ✅ |
| 7-4 | `ai/report_generator.py` — RAG + キャッシュ + LLM オーケストレーター | `ai/report_generator.py` | ✅ |
| 7-5 | `POST /incidents/{id}/report` エンドポイント | `api/routes/ai.py` | ✅ |
| 7-6 | `api/main.py` に AI コンポーネントを組み込み（`AI_ENABLED` 環境変数） | `api/main.py` | ✅ |
| 7-7 | UI: インシデント詳細画面に「AI レポートを生成」ボタンを追加 | `pages/IncidentDetail.tsx` | ✅ |
| 7-8 | テスト（chromadb/openai 不要、RAGStore はモック化） | `tests/test_ai_report.py` | ✅ |

### 主な環境変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `AI_ENABLED` | `false` | `true` にすると AI コンポーネントを初期化 |
| `LLM_PROVIDER` | `openai` | `openai` または `ollama` |
| `OPENAI_API_KEY` | — | OpenAI API キー |
| `OPENAI_MODEL` | `gpt-4o-mini` | 使用するモデル名 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama エンドポイント |
| `OLLAMA_MODEL` | `llama3` | Ollama モデル名 |
| `AI_RAG_PATH` | `.chromadb` | ChromaDB の永続化ディレクトリ |
| `AI_CACHE_TTL_DAYS` | `7` | キャッシュの有効期限（日） |

### 完了条件

- [x] `POST /incidents/{id}/report` でレポートが生成される
- [x] 同一フィンガープリントの 2 回目のリクエストはキャッシュから返る（LLM 呼び出しなし）
- [x] RAG に過去インシデントが蓄積され、類似事例がプロンプトに含まれる
- [x] `AI_ENABLED=false`（デフォルト）のとき既存動作に影響しない
- [x] UI に「AI レポートを生成」ボタンが表示され、Markdown レンダリングされる

---

## Phase 8: 推論エンジン強化 ✅ 完了

### 目的

現行の根本原因推論エンジンが持つ4つの構造的課題を段階的に解消し、集約精度・カバレッジ・応答速度を改善する。

### 背景と課題

| # | 課題 | 影響 |
|---|---|---|
| 1 | タイムウィンドウが固定（30秒）で因果順序を無視 | 最初に届いたログが根本原因でも同格扱い |
| 2 | イベントの重み付けがなく低深刻度ログが根本原因候補に混入 | 誤集約・誤通知 |
| 3 | フラッピングを検出できず繰り返し障害が複数インシデントになる | アラートストームを助長 |
| 4 | 完全クラッシュしたノードはログを送れないため根本原因として識別できない | 見逃し障害 |

### 実装タスク

| # | サブフェーズ | タスク | 対象ファイル | 状態 |
|---|---|---|---|---|
| 8-1 | A: タイムスタンプ優先度 | ウィンドウ内の `received_at` を見て根本原因候補が複数いる場合に最も早いものを優先 | `root_cause_inferencer.py` | ✅ |
| 8-2 | B: Severity フィルター | `INFERENCE_SEVERITY_THRESHOLD`（デフォルト NOTICE=5）を超えるログのみ推論に使用、低深刻度は記録のみ | `root_cause_inferencer.py`, `__main__.py` | ✅ |
| 8-3 | C: フラッピング検出 | 同一ノード × 同一 `%FAC-SEV-MNEM` が `FLAPPING_THRESHOLD`（デフォルト 3）回以上 → `Incident.status="FLAPPING"` | `models.py`, `root_cause_inferencer.py`, `incident_store.py` | ✅ |
| 8-4 | D: サイレントセカンダリ推論 | `logged_nodes` の共通祖先でログを出していないノードを「サイレント根本原因」として候補に追加 | `graph_engine.py`, `root_cause_inferencer.py` | ✅ |
| 8-5 | E: アダプティブタイムウィンドウ | 5 秒以内に 5 件以上のバーストを検知したとき `window_sec` を自動延長（最大 `WINDOW_SEC_MAX`） | `api/main.py`, `__main__.py` | ✅ |
| 8-6 | テスト | 各サブフェーズの動作シナリオを網羅 | `tests/test_root_cause.py`, `tests/test_adaptive_window.py` | ✅ |

### 各サブフェーズの設計詳細

#### 8-1: タイムスタンプ優先度（因果順序）

```python
# 根本原因候補が複数いる場合、最初に届いたノードを優先
first_seen = {m.hostname: m.received_at for m in reversed(messages)
              if graph.node_exists(m.hostname)}
root_causes.sort(key=lambda n: first_seen.get(n, now))
```

#### 8-2: Severity フィルター

```python
# 環境変数 INFERENCE_SEVERITY_THRESHOLD=5 (NOTICE)
# severity 0=EMERG … 7=DEBUG。値が小さいほど深刻。
active = [m for m in messages if m.severity <= threshold]
# active だけを推論に使い、除外されたものは raw_logs にのみ記録
```

#### 8-3: フラッピング検出

```python
# Incident.status の値を拡張
STATUS_OPEN      = "OPEN"
STATUS_RESOLVED  = "RESOLVED"
STATUS_FLAPPING  = "FLAPPING"  # 追加

# 同一ノード × 同一イベント種別が N 回以上 → FLAPPING
event_counts = Counter(
    (m.hostname, _extract_event_type(m.message))
    for m in messages if graph.node_exists(m.hostname)
)
flapping_nodes = {node for (node, _), cnt in event_counts.items()
                  if cnt >= FLAPPING_THRESHOLD}
```

#### 8-4: サイレントセカンダリ推論（最重要）

ログを送れなかった上流ノード（完全クラッシュ等）を根本原因として推論する。

```
状況: Spine1 がクラッシュしてログ送信不可
      Leaf1, Leaf2, Leaf3 が同時に %BGP-5-ADJCHANGE を報告

現状の推論:
  Leaf1, Leaf2, Leaf3 は互いに祖先を持たない → 3 件の独立インシデント（誤り）

改善後の推論:
  Leaf1, Leaf2, Leaf3 の共通祖先 = Spine1
  Spine1 はログを出していないが閾値（60%以上の子孫がログ）を超えている
  → Spine1 を「サイレント根本原因」と判定 → 1 件のインシデント
```

```python
def find_silent_root_candidates(
    logged_nodes: set[str],
    graph: GraphEngine,
    min_coverage: float = 0.6,
) -> list[str]:
    coverage: dict[str, int] = {}
    for node in logged_nodes:
        for ancestor in graph.get_ancestors(node):
            if ancestor not in logged_nodes:
                coverage[ancestor] = coverage.get(ancestor, 0) + 1
    threshold = max(2, int(len(logged_nodes) * min_coverage))
    return [n for n, cnt in coverage.items() if cnt >= threshold]
```

#### 8-5: アダプティブタイムウィンドウ

```python
BURST_WINDOW_SEC   = 5    # バースト判定ウィンドウ（秒）
BURST_THRESHOLD    = 5    # バースト判定件数
WINDOW_SEC_EXTEND  = 2.0  # バースト時にウィンドウを何倍に延長するか
WINDOW_SEC_MAX     = 120  # 最大ウィンドウ（秒）
```

### 完了条件

- [x] 8-1: 同一ウィンドウに複数の根本原因候補がいる場合、最初に到着したものが選ばれる
- [x] 8-2: `severity > threshold` のログは推論に使われず `raw_logs` にのみ記録される
- [x] 8-3: 同一ノードの同一イベントが 3 回以上来ると `FLAPPING` インシデントが生成される
- [x] 8-4: ログを出していない共通祖先ノードがサイレント根本原因として検出される
- [x] 8-5: バースト検知時にタイムウィンドウが自動延長される
- [x] 既存テスト（109件）がすべてパスすること

---

## Phase 9: 装置調査エージェント ✅ 完了

### 目的

インシデントが発生した際、実際のネットワーク装置に SSH 接続して状態情報を収集する。
どの装置にどのコマンドを実行するかは LLM が自律的に判断する **ReAct（Reasoning + Acting）エージェント**として実装する。

### アーキテクチャ

```
POST /incidents/{id}/investigation
        │
        ▼
InvestigationAgent.investigate(incident)
        │
        ├─ system prompt + インシデント情報 ─────────────────────────────┐
        │                                                                 │
        │  ReAct ループ（最大 8 ターン）                                  │
        │  ┌──────────────────────────────────────────────────────────┐  │
        │  │ LLM                                                       │  │
        │  │  ├─ get_topology_info(device_id) を呼ぶ                   │  │
        │  │  │       ↓ ToolDispatcher が GraphEngine から返答         │  │
        │  │  ├─ run_commands(device_id, commands[]) を呼ぶ            │  │
        │  │  │       ↓ DeviceConnector が pyATS で SSH 実行           │  │
        │  │  └─ 収集結果を受け取り、次のツール呼び出しを決定            │  │
        │  └──────────────────────────────────────────────────────────┘  │
        │                                                                 │
        └─ LLM が finish_reason="stop" を返したら最終レポートを生成 ──────┘
        │
        ▼
InvestigationReport を app.state.investigations に保存
WebSocket で investigation.done を配信
```

### 新規ファイル一覧

| ファイル | 役割 |
|---|---|
| `investigation/__init__.py` | パッケージ初期化（空） |
| `investigation/models.py` | `CommandResult`・`InvestigationReport` データクラス |
| `investigation/credential_store.py` | 装置認証情報の管理（環境変数 or YAML ファイル） |
| `investigation/testbed_builder.py` | yang_topology + 認証情報 → pyATS Testbed を動的生成 |
| `investigation/device_connector.py` | pyATS (unicon) で SSH 接続・コマンド実行。Genie パーサー対応 |
| `investigation/tools.py` | OpenAI tool スキーマ定義 + ToolDispatcher |
| `investigation/agent.py` | ReAct ループ本体（`InvestigationAgent`） |
| `api/routes/investigation.py` | `POST/GET /incidents/{id}/investigation` エンドポイント |

### 変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `ai/llm_client.py` | `chat_with_tools(messages, tools) -> dict` メソッドを `LLMClient`（抽象）・`OpenAIClient`・`OllamaClient` 各クラスに追加 |
| `topology/graph_engine.py` | `get_node_attrs(node_id)` / `get_direct_neighbors(node_id)` を追加 |
| `api/main.py` | トポロジー読み込み時に `app.state.topology_raw` へ生データを保存。investigation コンポーネントの初期化（`INVESTIGATION_ENABLED` で制御）とルーター登録を追加 |
| `api/routes/topology.py` | `POST /topology/reload` で `app.state.topology_raw` も更新するよう修正 |
| `__main__.py` | `INVESTIGATION_ENABLED` / `PYATS_TESTBED_FILE` / `INVESTIGATION_MAX_TURNS` / `INVESTIGATION_COMMAND_TIMEOUT` 環境変数を `create_app()` に渡すよう追加 |
| `requirements.txt` / `pyproject.toml` | `pyats>=24.0`・`genie>=24.0` を追加 |

### 装置接続の設計（pyATS）

`DeviceConnector` は pyATS の **unicon** で SSH 接続し、コマンドを実行する。

```python
# configs/clos/testbed.yaml を読み込んで接続
testbed = TestbedBuilder.build_for("Spine1")
device = testbed.devices["Spine1"]
device.connect(init_config_commands=[], log_stdout=False)

# Genie パーサーで構造化データを取得（対応コマンドのみ）
parsed = device.parse("show ip bgp summary")
# → Python dict。LLM が読みやすい構造化データとして CommandResult.parsed に格納

# Genie 未対応コマンドはフォールバックで生テキスト取得
output = device.execute("show logging")
```

**セキュリティ制御**: `show` / `display` / `ping` / `traceroute` で始まるコマンドのみ許可。それ以外はエラーとして拒否する（`_validate_command()` によるホワイトリスト制御）。

**pyATS は同期 API** のため `asyncio.to_thread()` でラップして FastAPI イベントループをブロックしない。

### 接続情報の管理（pyATS testbed YAML）

接続情報は **pyATS 標準の testbed YAML ファイル**（`configs/clos/testbed.yaml`）で一元管理する。
トポロジー定義（`yang_topology.yaml`）との混在を避けるため、ファイルは分離している。

```yaml
# configs/clos/testbed.yaml
testbed:
  name: agentic-ni-clos
  credentials:
    default:
      username: cisco
      password: cisco    # 本番では %ENV{DEVICE_PASSWORD} 等で環境変数化
    enable:
      password: cisco

devices:
  Spine1:
    os: iosv
    type: router
    connections:
      cli:
        protocol: ssh
        ip: 10.0.0.1       # Loopback0 — Ubuntu から BGP ファブリック経由で到達
        port: 22
  # Spine2, Leaf1, Leaf2, Leaf3 も同様
```

`TestbedBuilder` は起動時に testbed YAML を `yaml.safe_load()` で一度パースして保持し、
`build_for(device_id)` 呼び出しごとに `loader.load(dict)` で新規 Testbed インスタンスを生成する（スレッドセーフ）。

```bash
export PYATS_TESTBED_FILE=configs/clos/testbed.yaml
```

パスワードを環境変数で渡す場合は pyATS の `%ENV{VAR_NAME}` 記法が使える。

### エージェントが利用するツール

| ツール名 | 説明 | 引数 |
|---|---|---|
| `get_topology_info` | 指定デバイスの役割・隣接ノード・インターフェース一覧を返す | `device_id: str` |
| `run_commands` | SSH で装置に接続し show コマンドを実行して出力を返す | `device_id: str`, `commands: list[str]` |

LLM は以下のような判断を自律的に行う:

```
1. インシデントの根本原因ノードが Spine1 → get_topology_info("Spine1") で隣接構成を確認
2. BGP セッション障害のイベントタイプ → run_commands("Spine1", ["show ip bgp summary", "show ip interface brief"])
3. 出力に "Active" セッションがない → run_commands("Leaf1", ["show ip bgp summary"]) で対向も確認
4. 収集した情報をもとに障害概要・推奨対応を日本語でまとめる
```

### LLM の tool calling 対応

`chat_with_tools()` の戻り値スキーマ（`OpenAIClient` / `OllamaClient` 共通）:

```python
{
    "content": str | None,           # finish_reason="stop" 時の最終回答
    "finish_reason": str,             # "stop" | "tool_calls"
    "tool_calls": [                   # finish_reason="tool_calls" 時のみ
        {
            "id": str,
            "function": {"name": str, "arguments": str},  # arguments は JSON 文字列
        }
    ] | None,
}
```

Ollama は `/api/chat` エンドポイントでツール呼び出しをサポートするモデル（`llama3.1`・`qwen2.5` 等）が必要。

### API エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| `POST` | `/incidents/{id}/investigation` | 調査ジョブをバックグラウンドで開始（202相当） |
| `GET` | `/incidents/{id}/investigation` | 調査の進捗・結果を取得 |

`POST` は即座に `{"status": "running"}` を返し、調査はバックグラウンドタスクで実行される。
完了時は WebSocket で `investigation.done` イベントをブロードキャストする。

```json
// GET /incidents/INC-20260820-001/investigation
{
  "incident_id": "INC-20260820-001",
  "status": "completed",
  "started_at": "2026-08-20T10:00:00Z",
  "completed_at": "2026-08-20T10:02:35Z",
  "summary": "Spine1 の GigabitEthernet0/0 がダウンし...",
  "error": null,
  "commands": [
    {
      "device_id": "Spine1",
      "command": "show ip bgp summary",
      "output": "...",
      "timestamp": "2026-08-20T10:00:15Z",
      "error": null
    }
  ]
}
```

### 調査結果のストレージ

現フェーズでは `app.state.investigations: dict[str, InvestigationReport]` にオンメモリで保持する。
サーバー再起動で消えるが、運用中の調査結果は WebSocket で配信済みのため実用上の問題は少ない。
将来は DB への永続化（`incident_investigations` テーブル）を検討する。

### 主な環境変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `INVESTIGATION_ENABLED` | `false` | `true` で調査エージェントを有効化 |
| `PYATS_TESTBED_FILE` | — | pyATS testbed YAML ファイルのパス（`INVESTIGATION_ENABLED=true` の場合必須） |
| `INVESTIGATION_MAX_TURNS` | `8` | LLM エージェントの最大ターン数 |
| `INVESTIGATION_COMMAND_TIMEOUT` | `30` | SSH コマンドタイムアウト（秒） |

### 完了条件

- [x] `POST /incidents/{id}/investigation` で調査がバックグラウンド起動する
- [x] LLM が `get_topology_info` / `run_commands` ツールを使って自律的に調査を進める
- [x] pyATS で装置に SSH 接続してコマンド実行結果を取得できる
- [x] Genie パーサー対応コマンドは構造化データが `CommandResult.parsed` に格納される
- [x] `show` 以外のコマンドはホワイトリスト検証でエラーになる
- [x] 調査完了後に WebSocket で `investigation.done` が配信される
- [x] `INVESTIGATION_ENABLED=false`（デフォルト）のとき既存動作に影響しない
