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

> 最終更新: 2026-09-03

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
| Phase 10: 即時推論 + 既存インシデント統合 | ✅ 完了 | 10-1〜10-7 実装完了、回帰テスト 78 passed |
| Phase 11: SYSLOG Knowledge Base (SKB) | ✅ 完了 | 11-1〜11-8 実装完了、SKB 回帰テスト 41 passed |
| Phase 12: SYSLOG分類レイヤー強化 | ✅ 完了 | 12-1〜12-7 実装完了、Knowledge 回帰テスト 28 passed、frontend build passed |
| Phase 13: 復旧イベント対応 | ✅ 完了 | 13-1〜13-7 実装完了、Phase 13 回帰テスト 42 passed、frontend build passed |
| Phase 14: 説明可能なRCA + Confidence | ✅ 完了 | 14-1〜14-8 実装完了、Phase 14 回帰テスト 79 passed、frontend build passed |
| Phase 15: 影響範囲算出 | ⏳ 未着手 | トポロジーから拠点、VLAN、VRF、冗長性への影響を算出 |
| Phase 16: 共有前の運用完成度向上 | ✅ 完了 | 配布経路、認証、処理一貫性、耐久性、CI 検証を実装 |

---

## 実装フェーズ一覧

| フェーズ | 名称 | 目的 | 主な成果物 | 状態 |
|---|---|---|---|---|
| **Phase 0** | PoC | コアアルゴリズムの動作検証 | 初期PoC（削除済み） | ✅ 完了 |
| **Phase 1** | コアエンジン | 本番品質のログ受信・相関推論 | `src/topology_syslog/` パッケージ | ✅ 完了 |
| **Phase 2** | ストレージ & API | 永続化層とトポロジー管理API | PostgreSQL スキーマ、FastAPI サーバー | ✅ 完了 |
| **Phase 3** | 外部統合 | トポロジー同期・通知連携 | NETCONF/RESTCONF アダプター、Notifier | ✅ 完了 |
| **Phase 4** | UI / ダッシュボード | インシデント可視化 | React + Cytoscape.js フロントエンド | ✅ 完了 |
| **Phase 5** | 本番化 | 性能・セキュリティ・可用性 | 負荷テスト結果、本番 docker-compose | ⏳ 未着手 |
| **Phase 6** | BGPピアリングのグラフエッジ化 | iBGP等でトポロジーと一致しないピアもインシデント集約対象にする | `yang_topology.yaml`, `yang_loader.py`, `graph_engine.py`, フロントエンド | ✅ 完了 |
| **Phase 7** | AI 障害レポート | LLM による障害分析レポート自動生成（RAG + クエリキャッシュ） | `ai/` モジュール、`/incidents/{id}/report` API、UI ボタン | ✅ 完了 |
| **Phase 8** | 推論エンジン強化 | 集約精度・カバレッジ・応答速度を段階的に改善 | `root_cause_inferencer.py`, `graph_engine.py` | ✅ 完了 |
| **Phase 9** | 装置調査エージェント | インシデント発生時に実機へ SSH 接続して情報収集。どの装置にどのコマンドを実行するかを LLM が自律判断する ReAct エージェント | `investigation/` モジュール、`/incidents/{id}/investigation` API | ✅ 完了 |
| **Phase 10** | 即時推論 + 既存インシデント統合 | 30秒タイムウィンドウ待ちを廃止し、受信ごとに推論・既存インシデントへ統合する | `api/main.py`, `file_ingest.py`, `incident_store.py`, `incident_merger.py` | ✅ 完了 |
| **Phase 11** | SYSLOG Knowledge Base (SKB) | 既知/未知の SYSLOG を分類し、Severity を含む運用ポリシー、対処手順、承認済み知識を継続的に活用する | `knowledge/` モジュール、SKB YAML/DB、レビュー API/UI | ✅ 完了 |
| **Phase 12** | SYSLOG分類レイヤー強化 | 常時流れる SYSLOG を保存対象と推論対象へ分離し、ノイズや状態変化を安全に扱う | `knowledge/`, `ingestion/`, `correlation/`, `persistence/raw_log_store.py` | ✅ 完了 |
| **Phase 13** | 復旧イベント対応 | down/up や established/lost を状態遷移として扱い、インシデントを自動更新・自動クローズする | `correlation/`, `persistence/incident_store.py`, `api/main.py`, UI | ✅ 完了 |
| **Phase 14** | 説明可能なRCA + Confidence | 根本原因判定の根拠、代替候補、確信度を構造化し、API/UI/AIレポートへ展開する | `correlation/root_cause_inferencer.py`, `models.py`, `api/schemas.py`, UI | ✅ 完了 |
| **Phase 15** | 影響範囲算出 | トポロジー属性から影響拠点、VLAN、VRF、BGP peer、冗長性を算出する | `topology/graph_engine.py`, `correlation/`, `api/routes/`, UI | ⏳ 未着手 |
| **Phase 16** | 共有前の運用完成度向上 | 他利用者へ展開する前に、配布時の到達性・管理操作の保護・取込経路の一貫性・結果の耐久性を確立する | `frontend/`, `api/`, `ingestion/`, `investigation/`, `docker-compose.yml` | ✅ 完了 |

---

## ディレクトリ構造 (最終形)

```
topology-syslog/
├── README.concept.md
├── README.poc.md
├── README.implementation.md    ← 本ファイル
├── yang/                       # 既存 YANGモデル (iida-network-model)
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
│   │   │   ├── incident_merger.py       # 即時推論結果と既存インシデントの統合 (Phase 10)
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

## Phase 10: 即時推論 + 既存インシデント統合 ✅ 完了

### 目的

Phase 10 では、従来のがっつりしたタイムウィンドウバッファを廃止し、各 syslog を受信した段階で即座に相関・統合する。既存の OPEN インシデントへ吸収するマージ戦略と、後続の根本原因イベントでの昇格を一貫して扱う。

### 実装項目

| # | 実装内容 | 結果 |
|---|---|---|
| 10-1 | `IncidentMerger` による `NEW` / `APPEND` / `PROMOTE_ROOT` 判定 | ✅ |
| 10-2 | `IncidentStore` の `list_open_active()` / `append()` / `recover_by_root_cause()` を活用した統合 | ✅ |
| 10-3 | API 側で `time_window` 依存を廃止し、メッセージ受信ごとに `_process_message_immediately()` を呼ぶ | ✅ |
| 10-4 | 文件取り込みでも時間順に 1 メッセージずつ処理し、遅延 root cause の統合を保持 | ✅ |
| 10-5 | `CORRELATION_MODE` と旧 `WINDOW_SEC` 系設定の互換性・非推奨警告を整理 | ✅ |
| 10-6 | `incident.new` / `incident.updated` / `incident.recovered` のイベント分離と Vigil の重複通知抑止 | ✅ |
| 10-7 | 最終回帰テストと実装計画の状態更新 | ✅ |

### 検証結果

以下を実行し、Phase 10 の回帰を確認した。

```bash
cd /home/iida/git/topology-syslog && pytest -q src/tests/test_api.py src/tests/test_api_ingest.py src/tests/test_incident_merger.py src/tests/test_incident_store.py src/tests/test_root_cause.py src/tests/test_time_window.py src/tests/test_adaptive_window.py
```

結果:

- 78 passed
- 1 warning
- 0 failed

> warning は Starlette / httpx の非推奨互換警告で、Phase 10 の機能自体には影響しない。

---

## Phase 0: PoC (動作原理の検証) ✅ 完了

### 目的

根本原因推論アルゴリズムが正しく機能することを、最小構成で確認する。

### 実装タスク

| # | タスク | 詳細 | 状態 |
|---|---|---|---|
| 0-1 | PoCトポロジ作成 | `Core-Router1 → Dist-Switch1 → Access-SW1` の3ノードDAGを `iida-network-model` 形式で記述 | ✅ |
| 0-2 | PoCサービス実装 | UDP 514受信、10秒ウィンドウ、祖先探索、YANGモデル形式トポロジ読み込みを検証 | ✅ |
| 0-3 | PoCログ送信スクリプト作成 | 3機器から連鎖障害ログをUDP送信するシミュレータを検証 | ✅ |
| 0-4 | PoCコンテナ化 | 単一コンテナでの動作を検証 | ✅ |
| 0-5 | PoC動作確認 | 1件のインシデントへの集約を確認 | ✅ |
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
| 処理スループット | 10,000 EPS | SYSLOG 送信ツールの並列送信で負荷テスト |
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

---

## Phase 10: 即時推論 + 既存インシデント統合 🔄 進行中

### 目的

30秒のタイムウィンドウにログを蓄積してから推論する方式を廃止し、SYSLOG 受信ごとに即時推論する方式へ切り替える。
後続ログが同じ障害に属すると判断できる場合は、新規インシデントを作らず既存インシデントへ統合する。

### 背景と課題

| # | 現行方式の課題 | 影響 |
|---|---|---|
| 1 | 最初のログから `WINDOW_SEC` 秒待つ | 検知・通知・調査開始が遅れる |
| 2 | ウィンドウ境界で関連ログが分断される | 同一障害が複数インシデントになる |
| 3 | 常時ログが流れる環境ではバッファが肥大化する | 推論単位が大きくなり、誤集約しやすい |
| 4 | アダプティブ延長で待ち時間がさらに伸びる | 重大障害ほど初動が遅くなる可能性がある |

### 新方式の基本方針

```
SYSLOG 受信
  │
  ├─ 復旧イベントの場合
  │    └─ root_cause_node 一致の OPEN インシデントを RECOVERED に更新
  │
  └─ 障害イベントの場合
     ├─ 1件または短い関連集合として RootCauseInferencer.infer() を実行
     ├─ IncidentMerger が既存 OPEN インシデントとの関連性を判定
     ├─ 関連あり: 既存インシデントへ raw_logs / raw_log_count / secondary_nodes / condition を追記
     └─ 関連なし: 新規インシデントとして保存・通知
```

統合判定は、まず保守しやすいルールベースで実装する。

1. `root_cause_node` が一致する OPEN インシデントは統合対象。
2. 新規候補の根本原因が既存根本原因の子孫である場合、既存インシデントの二次影響として統合する。
3. 新規候補の根本原因が既存根本原因の祖先である場合、既存インシデントの root cause を上流側へ昇格して統合する。
4. メンテナンス計画に一致する候補は既存方式どおり `CLOSED` として扱い、通知を抑制する。
5. 復旧イベントは統合対象ではなく、既存インシデントの `condition` 更新に使う。

### 実装タスク

| # | サブフェーズ | タスク | 対象ファイル | 状態 |
|---|---|---|---|---|
| 10-1 | A: 統合ポリシー定義 | 新規候補 Incident と既存 OPEN Incident の統合可否・昇格ルールを `IncidentMerger` として実装 | `correlation/incident_merger.py` | ✅ |
| 10-2 | B: ストア更新 API | OPEN インシデント検索、既存インシデント更新、root cause 昇格を安全に行うメソッドを追加 | `persistence/incident_store.py` | ✅ |
| 10-3 | C: API 受信フロー変更 | `_consume_syslog()` から `buffer` / `flush_task` / アダプティブウィンドウ処理を外し、受信ごとに即時処理する | `api/main.py` | ⏳ |
| 10-4 | D: ファイル取り込み変更 | `_group_by_window()` 依存を廃止し、時刻順に1件ずつ推論・統合するバッチ処理へ変更 | `ingestion/file_ingest.py` | ⏳ |
| 10-5 | E: 設定整理 | `WINDOW_SEC` 系設定を互換用に残すか廃止するか決め、README / env 説明を更新する | `__main__.py`, `config.py`, `README.md` | ✅ |
| 10-6 | F: WebSocket/通知 | 新規作成時は `incident.new`、既存統合時は `incident.updated` を配信し、Vigil 通知の重複を抑制する | `api/main.py`, `api/schemas.py` | ⏳ |
| 10-7 | G: テスト | 統合、root cause 昇格、復旧、ファイル取り込み、既存ウィンドウ互換のテストを追加・更新する | `tests/test_incident_merger.py`, `tests/test_api.py`, `tests/test_api_ingest.py` | ⏳ |

### 10-1: IncidentMerger 設計

```python
class IncidentMerger:
  def find_merge_target(
    self,
    candidate: Incident,
    open_incidents: list[Incident],
    graph: GraphEngine,
  ) -> MergeDecision: ...

  def merge(
    self,
    target: Incident,
    candidate: Incident,
    graph: GraphEngine,
  ) -> Incident: ...
```

`MergeDecision` は以下の3種類を返す。

| 種類 | 意味 | 保存動作 |
|---|---|---|
| `NEW` | 統合対象なし | candidate を新規保存 |
| `APPEND` | 既存 root cause の配下ログ | target に raw log と secondary node を追記 |
| `PROMOTE_ROOT` | より上流の root cause が後から判明 | target の root cause を candidate 側へ更新し、旧 root cause を secondary に移す |

### 10-2: IncidentStore 追加メソッド案

```python
class IncidentStore:
  def list_open_active(self) -> list[Incident]: ...
  def update(self, incident: Incident) -> None: ...
```

既存の `save()` は `session.merge()` のため更新にも使えるが、Phase 10 では「新規保存」と「既存更新」を呼び出し側で明確に分ける。
必要であれば `append_to_incident()` のような用途特化メソッドを追加する。

### 10-3: API 受信フロー変更

現在の `_consume_syslog()` は以下の責務を持っている。

- `buffer` にメッセージを蓄積する
- `window_sec` 経過後にまとめて推論する
- バースト/ルーティングイベントでウィンドウを延長する
- 推論結果を保存・通知・WebSocket配信する
- 復旧イベントで既存インシデントの `condition` を更新する

Phase 10 では、保存・通知・復旧処理は維持し、蓄積と遅延フラッシュだけを削除する。

```python
while True:
  msg = await syslog_queue.get()
  app.state.syslog_recv_count += 1
  await _process_message_immediately(msg)
```

`_process_message_immediately()` は以下を担当する。

1. topology 未ロード時は警告して終了。
2. 復旧イベントなら `recover_by_root_cause()` を実行。
3. 障害イベントなら `infer([msg], graph)` を実行。
4. メンテナンス判定を行う。
5. `IncidentMerger` で既存 OPEN インシデントと統合する。
6. 新規なら保存・通知・`incident.new` 配信、統合なら保存・`incident.updated` 配信。

### 10-4: ファイル取り込み変更

バッチ処理では受信時刻順にソートして、1件ずつ API と同じ統合ロジックを通す。
これにより過去ログ処理でも「後から上流 root cause が判明した場合の昇格」を再現できる。

```python
for msg in sorted(messages, key=lambda m: m.received_at):
  result = process_candidate([msg], graph, inferencer, store, graph)
  total += 1 if result.created_new else 0
```

`run_stream()` も `asyncio.wait_for(..., timeout=window_sec)` による静穏待ちをやめ、読み込んだ行ごとに即時処理する。
EOF 時の残バッファ処理は不要になる。

### 互換性方針

Phase 10 完了時点では、環境変数 `WINDOW_SEC` / `BURST_WINDOW_SEC` / `BURST_THRESHOLD` / `WINDOW_EXTEND_FACTOR` / `WINDOW_SEC_MAX` は非推奨扱いにする。
削除は次フェーズ以降に回し、設定されていても即時推論モードでは使用しない。

将来的に比較運用が必要な場合は、以下のような明示設定を追加する。

```bash
CORRELATION_MODE=immediate  # immediate | time_window
```

ただし初回実装では分岐を増やさず、即時推論を標準動作として実装する。

### テストシナリオ

| シナリオ | 期待結果 |
|---|---|
| Spine1 の障害ログ後に Leaf1/Leaf2 の BGP ログが届く | 1件のインシデントに統合され、Leaf1/Leaf2 が secondary に入る |
| Leaf1/Leaf2 のログ後に Spine1 の障害ログが届く | 既存インシデントの root cause が Spine1 に昇格する |
| 無関係な Branch-Router のログが届く | 別インシデントとして新規作成される |
| 復旧イベントが届く | root_cause_node 一致の OPEN インシデントが RECOVERED になる |
| メンテナンス対象機器のログが届く | インシデントは CLOSED / maintenance_plan_id 設定済みになる |
| 同一ノード・同一イベントが連続する | raw_log_count が増え、必要に応じて FLAPPING が維持される |

### 完了条件

- [ ] UDP 受信で `WINDOW_SEC` 秒待たずにインシデントが作成・更新される
- [ ] 既存 root cause 配下の後続ログが `secondary_nodes` と `raw_logs` に統合される
- [ ] 後から上流ノードのログが届いた場合、root cause が上流へ昇格する
- [ ] ファイル取り込み・標準入力取り込みでもタイムウィンドウ分割を使わない
- [ ] `incident.updated` WebSocket イベントで UI が更新できる
- [ ] Vigil など外部通知で同一障害の重複通知が抑制される
- [x] 10-1: `IncidentMerger` が同一 root 追記、子孫追記、祖先昇格、無関係ログ分離を判定できる
- [x] 10-2: `IncidentStore` が統合候補の OPEN/ACTIVE 検索と既存行の明示更新を行える
- [ ] Phase 10 の新規/更新テストがすべてパスする

---

## Phase 11: SYSLOG Knowledge Base (SKB) ✅ 完了

### 目的

既知の SYSLOG には、承認済みの分類、Severity 別の対応方針、相関上の扱い、調査手順を適用する。未知の SYSLOG は既存ルールへ無理に当てはめず、発生状況と類似事例を蓄積し、運用者のレビュー後に知識として昇格できるようにする。

Severity は RFC 5424 の `0=EMERGENCY` から `7=DEBUG` をそのまま保持し、メッセージ種別の重要度とは分離して評価する。同種イベントでも Severity ごとに、通知、インシデント化、相関のみ、保存のみを切り替える。

### 基本フロー

```text
SYSLOG 受信
  -> パース（vendor / event_type / 正規化シグネチャ）
  -> SKB 照合
     -> known: Severity ポリシー、相関ロール、runbook を付与
     -> unknown: 未知イベントとして観測・類似検索・レビュー候補へ登録
  -> 即時相関・既存インシデント統合
  -> インシデントと運用者フィードバックを SKB へ反映
```

### 知識レコード

SKB はまず Git 管理できる YAML を正本とし、未知イベントの観測・レビュー結果は DB に保存する。YAML は起動時およびリロード時に読み込み、承認済みルールだけを自動判定に使用する。

```yaml
id: cisco-link-updown
vendor: cisco-ios
signature: "%LINK-*-UPDOWN"
classification: link-state-change
correlation_role: root-cause-candidate
severity_policy:
  "0-2": page_immediately
  "3": create_incident
  "4-5": correlate_only
  "6-7": retain_only
dedup_window_sec: 120
runbook:
  - "show interfaces <interface>"
  - "show logging | include <interface>"
status: approved
confidence: 0.95
```

`signature` は可変パラメーターを除いた正規化シグネチャとして扱う。たとえば `%BGP-3-ADJCHANGE` と `%BGP-5-ADJCHANGE` は同一イベント種別へ対応付け、Severity ポリシーで動作を分ける。

### 実装タスク

| # | サブフェーズ | タスク | 対象ファイル | 状態 |
|---|---|---|---|---|
| 11-1 | A: データモデル | `SyslogMessage` に `normalized_signature`、`knowledge_status`、`knowledge_id`、`recommended_action`、`knowledge_confidence` を追加し、未知イベントとレビュー結果の永続モデルを定義する | `models.py`, `persistence/` | ✅ |
| 11-2 | B: 正規化 | vendor/event_type/message から可変値と Severity を分離した正規化シグネチャを生成する。Cisco 以外は安全なフォールバックを持つ | `ingestion/syslog_parser.py`, `knowledge/normalizer.py` | ✅ |
| 11-3 | C: SKB 照合 | YAML スキーマ検証、承認済み知識のロード、優先順位付きマッチング、ホットリロードを実装する | `knowledge/store.py`, `knowledge/matcher.py`, `configs/syslog_knowledge/` | ✅ |
| 11-4 | D: Severity ポリシー | `page_immediately`、`create_incident`、`correlate_only`、`retain_only` を判定し、既存の推論閾値と整合させる | `knowledge/policy.py`, `api/main.py`, `correlation/` | ✅ |
| 11-5 | E: 未知イベント管理 | 未知シグネチャの件数、初回/最終観測時刻、代表ログ、Severity 分布、関連ノードを集約して保存する | `persistence/unknown_event_store.py`, `api/routes/knowledge.py` | ✅ |
| 11-6 | F: 類似事例とレビュー | 既存 RAG で類似インシデント・既知ルール候補を提示し、運用者が承認、抑制、runbook 更新を行える API/UI を追加する | `ai/rag_store.py`, `api/routes/knowledge.py`, `frontend/src/` | ✅ |
| 11-7 | G: 監査・運用 | 知識ルールの作成者、承認者、版、適用履歴を記録し、誤判定時にルールを無効化・ロールバック可能にする | `knowledge/`, `persistence/` | ✅ |
| 11-8 | H: テスト | 既知/未知分類、Severity 別アクション、ルール優先順位、承認前ルールの非適用、未知イベント集約、既存相関の回帰をテストする | `tests/test_knowledge.py`, `tests/test_api*.py` | ✅ |

### 実装順序と判断基準

1. 11-1〜11-3 を実装し、既知/未知を安全に識別する。この時点では既存のインシデント生成ロジックを変更しない。
2. 11-4 で `retain_only` を推論・通知から除外し、`correlate_only` は通知せず既存インシデントへの証跡として保持する。`page_immediately` は既存の通知経路を優先度付きで利用する。
3. 11-5〜11-6 で未知イベントを可視化し、人の承認を経て YAML の `approved` ルールへ昇格する。LLM/RAG の提案だけで自動承認しない。
4. 11-7 は変更監査を必須にし、知識の誤適用が障害対応を妨げた場合に即時停止できるようにする。

### API 案

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/knowledge/rules` | 承認済み・保留・無効の SKB ルールを一覧する |
| `POST` | `/knowledge/rules` | 新規ルールを保留状態で登録する |
| `POST` | `/knowledge/rules/{id}/approve` | レビュー済みルールを承認し、照合対象にする |
| `POST` | `/knowledge/rules/{id}/disable` | ルールを即時無効化する |
| `GET` | `/knowledge/unknown-events` | 未知シグネチャを発生件数・Severity・最終観測時刻で一覧する |
| `GET` | `/knowledge/unknown-events/{signature}/suggestions` | RAG による類似インシデント・ルール候補を取得する |

### テストシナリオ

| シナリオ | 期待結果 |
|---|---|
| 承認済み `%LINK-*-UPDOWN` を受信する | `knowledge_status=known` となり、対応する相関ロールと runbook が付与される |
| 同一イベント種別で Severity 3 と 6 を受信する | Severity 3 はインシデント候補、6 は `retain_only` として保存のみになる |
| 未登録の高 Severity メッセージを受信する | `knowledge_status=unknown` として未知イベントに集約され、要レビューのインシデント候補になる |
| 未登録の低 Severity メッセージを繰り返し受信する | 通知せず未知イベントの頻度・Severity 分布を更新する |
| 保留または無効状態のルールに一致する | 自動ポリシーは適用せず未知イベントとして扱う |
| 類似する過去インシデントが存在する | レビュー画面/APIで候補として提示するが、自動承認はしない |
| SKB が未設定または読込不能である | 既存のパース・相関・通知フローを継続し、エラーを記録する |

### 完了条件

- [x] 既知 SYSLOG に承認済みの分類、Severity ポリシー、相関ロール、runbook を付与できる
- [x] 正規化シグネチャにより、可変値や Severity が異なる同種イベントを同じ知識へ対応付けられる
- [x] Severity ごとに通知、インシデント化、相関のみ、保存のみを切り替えられる
- [x] 未知 SYSLOG を既知ルールとして誤適用せず、発生状況を永続的に集約できる
- [x] 未知の高 Severity イベントを要レビューとして追跡できる
- [x] RAG は類似候補の提示に限定され、運用者の承認なしにルールを自動有効化しない
- [x] ルールの承認・無効化・適用履歴を監査できる
- [x] SKB 未設定時に既存の即時推論・インシデント統合が回帰しない
- [x] `pytest -q src/tests/test_knowledge.py src/tests/test_api.py src/tests/test_api_ingest.py` がパスする（41 passed）

---

## Phase 12: SYSLOG分類レイヤー強化 ✅ 完了

### 目的

常時 SYSLOG が流れる環境でも、相関エンジンが全ログを障害候補として扱わないようにする。
受信したログをまず運用上の意味へ分類し、「保存するログ」と「根本原因推論に使うイベント」を分離する。

### 基本方針

```text
SYSLOG 受信
  -> RFC / vendor parser
  -> SKB 正規化・照合
  -> EventClassifier
   -> noise: 保存のみ
   -> retain-only: 保存のみ
   -> state-change: 状態更新または相関証跡
   -> fault-signal: インシデント推論対象
   -> recovery: Phase 13 の復旧処理へ渡す
   -> config-change: Change / Maintenance 相関へ渡す
   -> security: 監査・通知ポリシーへ渡す
  -> Correlation Pipeline
```

分類は SKB の `classification` / `correlation_role` / `severity_policy` を第一優先にし、未登録 SYSLOG は安全側に倒す。
未知の高 Severity イベントはレビュー対象として残し、未知の低 Severity イベントは通知せず頻度と代表ログを蓄積する。

### 分類カテゴリ

| カテゴリ | 例 | 推論上の扱い |
|---|---|---|
| `noise` | periodic informational message, debug, benign auth notice | 生ログ保存のみ |
| `retain-only` | 低 Severity の既知イベント | 生ログ保存、未知イベント集計のみ |
| `state-change` | interface up/down, protocol neighbor state | 状態テーブル更新、条件次第で推論対象 |
| `fault-signal` | link down, BGP down, PSU failure, fan failure | 根本原因推論対象 |
| `recovery` | link up, BGP established, HA restored | 既存インシデントの復旧判定へ利用 |
| `config-change` | config commit, reload, user change | Change / Maintenance と相関 |
| `security` | login failure, privilege escalation, ACL deny burst | セキュリティ通知または別カテゴリのインシデント |

### 実装タスク

| # | サブフェーズ | タスク | 対象ファイル | 状態 |
|---|---|---|---|---|
| 12-1 | A: 分類モデル | `EventClassification`、`EventAction`、分類理由を表すデータモデルを追加する | `models.py`, `knowledge/` | ✅ |
| 12-2 | B: 分類器 | SKB ルール、Severity、event_type、vendor を使う `EventClassifier` を実装する | `knowledge/classifier.py`, `knowledge/policy.py` | ✅ |
| 12-3 | C: 推論入口分離 | `fault-signal` のみ新規インシデント候補にし、`state-change` / `config-change` は証跡または補助シグナルとして扱う | `api/main.py`, `correlation/` | ✅ |
| 12-4 | D: Raw Log 保存方針 | 推論対象外のログも検索・監査できるよう、分類結果付きで保存する | `persistence/raw_log_store.py`, `api/routes/` | ✅ |
| 12-5 | E: 未知イベント連携 | 未知イベント集約に分類候補、代表 Severity、推奨アクションを追加する | `persistence/unknown_event_store.py`, `api/routes/knowledge.py` | ✅ |
| 12-6 | F: UI | Knowledge Review 画面で分類カテゴリと推論対象/保存のみをレビューできるようにする | `frontend/src/pages/KnowledgeReview.tsx` | ✅ |
| 12-7 | G: テスト | 分類、保存のみ、推論対象、未知イベント、既存 SKB 回帰をテストする | `src/tests/test_knowledge.py`, `src/tests/test_api_ingest.py` | ✅ |

### テストシナリオ

| シナリオ | 期待結果 |
|---|---|
| 既知の低 Severity informational を受信する | `retain-only` として保存され、インシデントは作成されない |
| 既知の link down を受信する | `fault-signal` として即時推論へ渡される |
| 既知の link up を受信する | 新規インシデントを作らず `recovery` として Phase 13 の処理へ渡される |
| 未知の Severity 3 イベントを受信する | 未知イベントとして集約され、要レビュー候補になる |
| 未知の Severity 6 イベントを大量に受信する | 通知せず頻度・代表ログを更新し、相関エンジンへ流さない |

### 完了条件

- [x] SYSLOG メッセージに分類カテゴリ、分類後アクション、分類理由を保持できる
- [x] SKB ルール、Severity、event_type、vendor から分類結果を生成できる
- [x] SYSLOG 受信後に必ず分類結果が付与される
- [x] `noise` / `retain-only` が新規インシデントを作成しない
- [x] `fault-signal` だけが根本原因推論の主入力になる
- [x] 推論対象外ログも分類結果付きで保存・検索できる
- [x] 未知イベントに分類候補、代表 Severity、推奨アクションを保存・API表示できる
- [x] 未知イベントレビューで分類カテゴリを選択し、保留ルールへ反映できる
- [x] 既存の SKB ポリシーと即時推論が回帰しない

### 12-1 検証結果

```bash
python -m pytest -q src/tests/test_knowledge.py::test_event_classification_model_defaults_to_unknown src/tests/test_knowledge.py::test_event_classification_result_carries_action_and_reasons
```

結果:

- 2 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、12-1 の分類モデルには影響しない。

### 12-2 検証結果

```bash
python -m pytest -q src/tests/test_knowledge.py::test_event_classifier_uses_skb_classification_and_severity_policy src/tests/test_knowledge.py::test_event_classifier_falls_back_to_review_for_unknown_message src/tests/test_knowledge.py::test_event_classifier_maps_root_cause_role_to_fault_signal
```

結果:

- 3 passed
- 1 warning

API 起動に依存しない Knowledge 周辺の回帰として、以下も確認した。

```bash
python -m pytest -q src/tests/test_knowledge.py::test_event_classification_model_defaults_to_unknown src/tests/test_knowledge.py::test_event_classification_result_carries_action_and_reasons src/tests/test_knowledge.py::test_parser_normalizes_cisco_event_without_severity src/tests/test_knowledge.py::test_matcher_applies_only_approved_rule src/tests/test_knowledge.py::test_matcher_uses_highest_priority_matching_rule src/tests/test_knowledge.py::test_pending_rule_is_not_applied src/tests/test_knowledge.py::test_severity_policy_resolves_individual_and_range_actions src/tests/test_knowledge.py::test_event_classifier_uses_skb_classification_and_severity_policy src/tests/test_knowledge.py::test_event_classifier_falls_back_to_review_for_unknown_message src/tests/test_knowledge.py::test_event_classifier_maps_root_cause_role_to_fault_signal
```

結果:

- 10 passed
- 1 warning

### 12-3 検証結果

```bash
python -m pytest -q src/tests/test_knowledge.py::test_process_message_skips_non_fault_classification_for_new_incident src/tests/test_knowledge.py::test_process_message_allows_fault_signal_to_create_new_incident src/tests/test_knowledge.py::test_ingest_endpoint_returns_only_created_fault_signal_incidents
```

結果:

- 3 passed
- 1 warning

Phase 12 前半の主要回帰として、以下も確認した。

```bash
python -m pytest -q src/tests/test_knowledge.py::test_event_classification_model_defaults_to_unknown src/tests/test_knowledge.py::test_event_classification_result_carries_action_and_reasons src/tests/test_knowledge.py::test_parser_normalizes_cisco_event_without_severity src/tests/test_knowledge.py::test_matcher_applies_only_approved_rule src/tests/test_knowledge.py::test_matcher_uses_highest_priority_matching_rule src/tests/test_knowledge.py::test_pending_rule_is_not_applied src/tests/test_knowledge.py::test_severity_policy_resolves_individual_and_range_actions src/tests/test_knowledge.py::test_event_classifier_uses_skb_classification_and_severity_policy src/tests/test_knowledge.py::test_event_classifier_falls_back_to_review_for_unknown_message src/tests/test_knowledge.py::test_event_classifier_maps_root_cause_role_to_fault_signal src/tests/test_knowledge.py::test_process_message_skips_non_fault_classification_for_new_incident src/tests/test_knowledge.py::test_process_message_allows_fault_signal_to_create_new_incident src/tests/test_knowledge.py::test_ingest_endpoint_returns_only_created_fault_signal_incidents
```

結果:

- 13 passed
- 1 warning

### 12-4 検証結果

```bash
python -m pytest -q src/tests/test_knowledge.py::test_raw_log_store_records_classification_metadata src/tests/test_knowledge.py::test_ingest_endpoint_stores_non_inferred_raw_logs
```

結果:

- 2 passed
- 1 warning

Phase 12-1〜12-4 の主要回帰として、以下も確認した。

```bash
python -m pytest -q src/tests/test_knowledge.py::test_event_classification_model_defaults_to_unknown src/tests/test_knowledge.py::test_event_classification_result_carries_action_and_reasons src/tests/test_knowledge.py::test_parser_normalizes_cisco_event_without_severity src/tests/test_knowledge.py::test_matcher_applies_only_approved_rule src/tests/test_knowledge.py::test_matcher_uses_highest_priority_matching_rule src/tests/test_knowledge.py::test_pending_rule_is_not_applied src/tests/test_knowledge.py::test_severity_policy_resolves_individual_and_range_actions src/tests/test_knowledge.py::test_event_classifier_uses_skb_classification_and_severity_policy src/tests/test_knowledge.py::test_event_classifier_falls_back_to_review_for_unknown_message src/tests/test_knowledge.py::test_event_classifier_maps_root_cause_role_to_fault_signal src/tests/test_knowledge.py::test_process_message_skips_non_fault_classification_for_new_incident src/tests/test_knowledge.py::test_process_message_allows_fault_signal_to_create_new_incident src/tests/test_knowledge.py::test_ingest_endpoint_returns_only_created_fault_signal_incidents src/tests/test_knowledge.py::test_raw_log_store_records_classification_metadata src/tests/test_knowledge.py::test_ingest_endpoint_stores_non_inferred_raw_logs
```

結果:

- 15 passed
- 1 warning

### 12-5 検証結果

```bash
python -m pytest -q src/tests/test_knowledge.py::test_unknown_event_store_records_classification_candidate_and_recommended_action src/tests/test_knowledge.py::test_unknown_event_api_includes_classification_candidate
```

結果:

- 2 passed
- 1 warning

Phase 12-1〜12-5 の主要回帰として、以下も確認した。

```bash
python -m pytest -q src/tests/test_knowledge.py::test_event_classification_model_defaults_to_unknown src/tests/test_knowledge.py::test_event_classification_result_carries_action_and_reasons src/tests/test_knowledge.py::test_parser_normalizes_cisco_event_without_severity src/tests/test_knowledge.py::test_matcher_applies_only_approved_rule src/tests/test_knowledge.py::test_matcher_uses_highest_priority_matching_rule src/tests/test_knowledge.py::test_pending_rule_is_not_applied src/tests/test_knowledge.py::test_severity_policy_resolves_individual_and_range_actions src/tests/test_knowledge.py::test_event_classifier_uses_skb_classification_and_severity_policy src/tests/test_knowledge.py::test_event_classifier_falls_back_to_review_for_unknown_message src/tests/test_knowledge.py::test_event_classifier_maps_root_cause_role_to_fault_signal src/tests/test_knowledge.py::test_process_message_skips_non_fault_classification_for_new_incident src/tests/test_knowledge.py::test_process_message_allows_fault_signal_to_create_new_incident src/tests/test_knowledge.py::test_ingest_endpoint_returns_only_created_fault_signal_incidents src/tests/test_knowledge.py::test_raw_log_store_records_classification_metadata src/tests/test_knowledge.py::test_ingest_endpoint_stores_non_inferred_raw_logs src/tests/test_knowledge.py::test_unknown_event_store_aggregates_signature_severity_and_nodes src/tests/test_knowledge.py::test_unknown_event_store_records_classification_candidate_and_recommended_action src/tests/test_knowledge.py::test_unknown_event_api_includes_classification_candidate
```

結果:

- 18 passed
- 1 warning

### 12-7 検証結果

Knowledge / 分類レイヤーの回帰として以下を実行した。

```bash
python -m pytest -q src/tests/test_knowledge.py
```

結果:

- 28 passed
- 1 warning

フロントエンド UI の回帰として以下も実行した。

```bash
cd frontend && npm run build
```

結果:

- build passed
- Vite CJS Node API の非推奨警告とチャンクサイズ警告が出るが、ビルド自体は成功

### 12-6 検証結果

`frontend/src/pages/KnowledgeReview.tsx` と `frontend/src/types.ts` のエラーチェックで問題なし。

フロントエンド全体のビルド確認として以下を実行した。

```bash
npm run build
```

結果:

- build passed
- Vite CJS Node API の非推奨警告とチャンクサイズ警告が出るが、ビルド自体は成功

---

## Phase 13: 復旧イベント対応 ✅ 完了

### 目的

障害イベントだけでなく復旧イベントを理解し、インシデントの状態を自動更新する。
単純な `OPEN` / `CLOSED` だけでなく、継続中、部分復旧、復旧確認中、フラッピングを区別する。

### インシデント状態案

| 状態 | 意味 |
|---|---|
| `OPEN` | 障害が発生し、まだ復旧シグナルがない |
| `DEGRADED` | 一部ノードまたは一部サービスのみ復旧していない |
| `RECOVERING` | 復旧イベントを検知し、静穏確認中 |
| `RECOVERED` | 復旧条件を満たしたが、履歴として保持中 |
| `FLAPPING` | down/up が短時間に繰り返されている |
| `CLOSED` | 自動または手動でクローズ済み |

### 基本方針

1. Phase 12 の `recovery` 分類を受け取り、既存 OPEN インシデントに対応付ける。
2. root cause node、secondary node、interface、peer、event signature を使って復旧対象を特定する。
3. 復旧イベント直後に即クローズせず、短い静穏期間を置いて `RECOVERED` または `CLOSED` に遷移する。
4. 静穏期間中に同種の障害イベントが再発した場合は `FLAPPING` に遷移する。
5. 手動クローズやメンテナンス自動クローズとの整合性を保つ。

### 実装タスク

| # | サブフェーズ | タスク | 対象ファイル | 状態 |
|---|---|---|---|---|
| 13-1 | A: 状態モデル | インシデント状態、復旧対象、最後の障害/復旧時刻、フラップ回数をモデル化する | `models.py`, `persistence/incident_store.py` | ✅ |
| 13-2 | B: 復旧マッチング | recovery event を既存インシデントの root / secondary / interface / peer に対応付ける | `correlation/recovery_matcher.py` | ✅ |
| 13-3 | C: 状態遷移 | `OPEN`、`RECOVERING`、`RECOVERED`、`FLAPPING` の遷移ルールを実装する | `correlation/incident_lifecycle.py` | ✅ |
| 13-4 | D: 静穏確認 | 復旧後の hold-down / quiet period を設定可能にし、再発時はクローズしない | `api/main.py`, `config.py` | ✅ |
| 13-5 | E: 通知 | 新規障害、部分復旧、完全復旧、フラッピングで通知種別を分ける | `notification/`, `api/schemas.py` | ✅ |
| 13-6 | F: UI | インシデント詳細に状態遷移タイムラインと復旧証跡を表示する | `frontend/src/pages/IncidentDetail.tsx` | ✅ |
| 13-7 | G: テスト | 復旧、部分復旧、再発、フラッピング、手動クローズとの競合をテストする | `src/tests/test_incident_store.py`, `src/tests/test_api_ingest.py` | ✅ |

### テストシナリオ

| シナリオ | 期待結果 |
|---|---|
| link down 後に同一 interface の link up を受信する | 対象インシデントが `RECOVERING` へ遷移する |
| quiet period 中に再度 link down を受信する | `OPEN` または `FLAPPING` へ戻り、自動クローズしない |
| root は復旧したが secondary の BGP down が残る | `DEGRADED` として残り、影響ノードが更新される |
| BGP down 後に established を受信する | 対応 peer の復旧証跡が追加される |
| 手動 CLOSED 済みインシデントに復旧イベントが届く | 再オープンせず、監査ログに追記する |

### 完了条件

- [x] インシデントに状態遷移用の時刻、フラップ回数、復旧証跡を保存できる
- [ ] 復旧イベントが新規インシデントを作らない
- [x] 復旧イベントを対応する既存インシデントの root / secondary / interface / peer に対応付けできる
- [x] 復旧イベントが対応する既存インシデントへ証跡として保存される
- [x] quiet period 後に自動で `RECOVERED` へ遷移できる
- [x] 再発時に `FLAPPING` を検知できる
- [x] 復旧・再発の状態遷移を通知イベント種別として外部連携できる
- [x] 手動クローズ済みインシデントが遅延復旧イベントで再オープンされない
- [x] UI が状態遷移と復旧証跡を表示できる
- [x] WebSocket が状態更新をリアルタイム表示できる

### 13-1 検証結果

```bash
python -m pytest -q src/tests/test_incident_store.py::test_incident_lifecycle_fields_are_persisted src/tests/test_incident_store.py::test_update_persists_incident_lifecycle_fields
```

結果:

- 2 passed
- 1 warning

IncidentStore 全体の回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py
```

結果:

- 15 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、13-1 の状態モデルには影響しない。

### 13-2 検証結果

```bash
python -m pytest -q src/tests/test_recovery_matcher.py
```

結果:

- 4 passed
- 1 warning

Phase 13 前半の回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py src/tests/test_recovery_matcher.py
```

結果:

- 19 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、13-2 の復旧マッチングには影響しない。

### 13-3 検証結果

```bash
python -m pytest -q src/tests/test_incident_lifecycle.py
```

結果:

- 5 passed
- 1 warning

Phase 13-1〜13-3 の回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py src/tests/test_recovery_matcher.py src/tests/test_incident_lifecycle.py
```

結果:

- 24 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、13-3 の状態遷移には影響しない。

### 13-4 検証結果

```bash
python -m pytest -q src/tests/test_incident_store.py::test_list_open_lifecycle_returns_recovery_candidates src/tests/test_incident_lifecycle.py::test_fault_after_recovery_seen_prevents_recovered_confirmation src/tests/test_knowledge.py::test_process_recovery_updates_incident_to_recovering_then_recovered src/tests/test_knowledge.py::test_fault_during_quiet_period_keeps_incident_unrecovered
```

結果:

- 4 passed
- 1 warning

Phase 13-1〜13-4 の回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py src/tests/test_recovery_matcher.py src/tests/test_incident_lifecycle.py src/tests/test_knowledge.py::test_process_recovery_updates_incident_to_recovering_then_recovered src/tests/test_knowledge.py::test_fault_during_quiet_period_keeps_incident_unrecovered
```

結果:

- 28 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、13-4 の静穏確認には影響しない。

### 13-5 検証結果

```bash
python -m pytest -q src/tests/test_notification.py
```

結果:

- 12 passed
- 1 warning

Phase 13-1〜13-5 の回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py src/tests/test_recovery_matcher.py src/tests/test_incident_lifecycle.py src/tests/test_notification.py src/tests/test_knowledge.py::test_process_recovery_updates_incident_to_recovering_then_recovered src/tests/test_knowledge.py::test_fault_during_quiet_period_keeps_incident_unrecovered
```

結果:

- 40 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、13-5 の通知種別には影響しない。

### 13-6 検証結果

```bash
cd frontend && npm run build
```

結果:

- build passed
- Vite CJS Node API の非推奨警告とチャンクサイズ警告が出るが、ビルド自体は成功

### 13-7 検証結果

```bash
python -m pytest -q src/tests/test_knowledge.py::test_recovery_lifecycle_broadcasts_recovering_and_recovered src/tests/test_knowledge.py::test_manual_closed_incident_ignores_late_recovery
```

結果:

- 2 passed
- 1 warning

Phase 13 全体の回帰として以下を確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py src/tests/test_recovery_matcher.py src/tests/test_incident_lifecycle.py src/tests/test_notification.py src/tests/test_knowledge.py::test_process_recovery_updates_incident_to_recovering_then_recovered src/tests/test_knowledge.py::test_fault_during_quiet_period_keeps_incident_unrecovered src/tests/test_knowledge.py::test_recovery_lifecycle_broadcasts_recovering_and_recovered src/tests/test_knowledge.py::test_manual_closed_incident_ignores_late_recovery
```

結果:

- 42 passed
- 1 warning

フロントエンド UI の回帰として以下も確認した。

```bash
cd frontend && npm run build
```

結果:

- build passed
- Vite CJS Node API の非推奨警告とチャンクサイズ警告が出るが、ビルド自体は成功

---

## Phase 14: 説明可能なRoot Cause Analysis + Confidence ✅ 完了

### 目的

根本原因推論の結果に、判断根拠、代替候補、確信度を付与する。
運用者が「なぜこの機器が root cause なのか」を確認でき、AI レポートにも同じ根拠を渡せるようにする。

### RCA Explanation モデル案

```python
@dataclass
class RCAEvidence:
  source: str              # topology | syslog | skb | maintenance | investigation
  summary: str
  weight: float
  related_nodes: list[str]
  related_log_ids: list[str]

@dataclass
class RCACandidate:
  node_id: str
  confidence: float
  evidences: list[RCAEvidence]
  secondary_nodes: list[str]
  alternative_reason: str | None = None
```

### 確信度の初期方針

初期実装では ML ではなく、説明しやすいルールベースのスコアにする。

| 要素 | 加点例 |
|---|---|
| 自身が `fault-signal` を出している | +0.30 |
| 下流ノードから関連ログが複数出ている | +0.20 |
| トポロジー上の ancestor に同時障害ログがない | +0.15 |
| SKB の knowledge confidence が高い | +0.15 |
| メンテナンス対象外である | +0.05 |
| 装置調査で異常状態が確認された | +0.15 |

スコアは 0.0〜1.0 に正規化し、UI では `High` / `Medium` / `Low` のラベルも併記する。

### 実装タスク

| # | サブフェーズ | タスク | 対象ファイル | 状態 |
|---|---|---|---|---|
| 14-1 | A: 説明モデル | `RCAEvidence`、`RCACandidate`、`confidence`、`alternative_candidates` をモデル化する | `models.py`, `api/schemas.py` | ✅ |
| 14-2 | B: 推論器拡張 | `RootCauseInferencer` が root cause だけでなく候補リストと根拠を返すようにする | `correlation/root_cause_inferencer.py` | ✅ |
| 14-3 | C: スコアリング | トポロジー、SKB、Severity、ログ件数、調査結果を使うルールベーススコアを実装する | `correlation/confidence.py` | ✅ |
| 14-4 | D: 永続化 | インシデントに RCA explanation JSON を保存し、再評価履歴を残す | `persistence/incident_store.py` | ✅ |
| 14-5 | E: API | インシデント詳細 API に根拠、代替候補、confidence を含める | `api/routes/incidents.py`, `api/schemas.py` | ✅ |
| 14-6 | F: UI | インシデント詳細に「判定根拠」「代替候補」「確信度」を表示する | `frontend/src/pages/IncidentDetail.tsx`, `frontend/src/components/IncidentCard.tsx` | ✅ |
| 14-7 | G: AI連携 | AI 障害レポート生成時に RCA explanation をプロンプトコンテキストへ含める | `ai/report_generator.py` | ✅ |
| 14-8 | H: テスト | スコア、根拠、代替候補、APIレスポンス、既存推論回帰をテストする | `src/tests/test_root_cause.py`, `src/tests/test_ai_report.py`, `src/tests/test_api.py` | ✅ |

### テストシナリオ

| シナリオ | 期待結果 |
|---|---|
| Spine と複数 Leaf が同時に fault-signal を出す | Spine が High confidence の root cause になる |
| Leaf だけが単独で障害ログを出す | Leaf が root cause だが confidence は Medium 以下になる |
| 上流候補が複数ある | alternative candidates に候補と理由が残る |
| SKB confidence が低い未知イベントを含む | RCA confidence が過剰に高くならない |
| 装置調査で root cause 候補の異常が確認される | evidence が追加され confidence が上がる |

### 完了条件

- [x] `RCAEvidence`、`RCACandidate`、`RCAExplanation` をモデル化し、インシデントに保持できる
- [x] 新規インシデントに root cause 候補、判断根拠、代替候補の RCA explanation が付与される
- [x] すべての新規インシデントにスコアリング済み `confidence` が保存される
- [x] 根本原因の判断根拠を API で取得できる
- [x] 代替候補と採用されなかった理由を確認できる
- [x] UI で判定根拠、代替候補、確信度、再評価履歴を確認できる
- [x] AI レポートが推論根拠を利用できる
- [x] confidence は再評価時に更新履歴を残す
- [x] 既存の root cause 判定結果が意図せず変わらない

### 14-1 検証結果

```bash
python -m pytest -q src/tests/test_incident_store.py::test_save_and_get_persists_rca_explanation src/tests/test_incident_store.py::test_incident_out_includes_rca_explanation
```

結果:

- 2 passed
- 1 warning

IncidentStore 全体の回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py
```

結果:

- 18 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、14-1 のRCA説明モデルには影響しない。

### 14-2 検証結果

```bash
python -m pytest -q src/tests/test_root_cause.py::test_inferencer_attaches_rca_explanation_to_incident src/tests/test_root_cause.py::test_silent_root_rca_explanation_uses_topology_evidence
```

結果:

- 2 passed
- 1 warning

14-1 / 14-2 の関連回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_root_cause.py::test_inferencer_attaches_rca_explanation_to_incident src/tests/test_root_cause.py::test_silent_root_rca_explanation_uses_topology_evidence src/tests/test_incident_store.py
```

結果:

- 20 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、14-2 の推論器拡張には影響しない。

### 14-3 検証結果

```bash
python -m pytest -q src/tests/test_root_cause.py::test_rca_confidence_scores_topology_and_syslog_evidence src/tests/test_root_cause.py::test_silent_root_confidence_is_medium_but_not_zero
```

結果:

- 2 passed
- 1 warning

14-1〜14-3 の関連回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_root_cause.py::test_inferencer_attaches_rca_explanation_to_incident src/tests/test_root_cause.py::test_silent_root_rca_explanation_uses_topology_evidence src/tests/test_root_cause.py::test_rca_confidence_scores_topology_and_syslog_evidence src/tests/test_root_cause.py::test_silent_root_confidence_is_medium_but_not_zero src/tests/test_incident_store.py
```

結果:

- 22 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、14-3 のスコアリングには影響しない。

### 14-4 検証結果

```bash
python -m pytest -q src/tests/test_incident_store.py::test_record_rca_evaluation_updates_current_explanation_and_history src/tests/test_incident_store.py::test_record_rca_evaluation_missing_incident_returns_none
```

結果:

- 2 passed
- 1 warning

14-1〜14-4 の関連回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py src/tests/test_root_cause.py::test_inferencer_attaches_rca_explanation_to_incident src/tests/test_root_cause.py::test_silent_root_rca_explanation_uses_topology_evidence src/tests/test_root_cause.py::test_rca_confidence_scores_topology_and_syslog_evidence src/tests/test_root_cause.py::test_silent_root_confidence_is_medium_but_not_zero
```

結果:

- 24 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、14-4 のRCA再評価履歴には影響しない。

### 14-5 検証結果

```bash
python -m pytest -q src/tests/test_api.py::test_get_incident_includes_rca_explanation_without_topology_fixture src/tests/test_api.py::test_get_rca_history_returns_evaluations_without_topology_fixture src/tests/test_api.py::test_get_rca_history_missing_incident_returns_404_without_topology_fixture
```

結果:

- 3 passed
- 1 warning

14-1〜14-5 の関連回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_incident_store.py src/tests/test_root_cause.py::test_inferencer_attaches_rca_explanation_to_incident src/tests/test_root_cause.py::test_silent_root_rca_explanation_uses_topology_evidence src/tests/test_root_cause.py::test_rca_confidence_scores_topology_and_syslog_evidence src/tests/test_root_cause.py::test_silent_root_confidence_is_medium_but_not_zero src/tests/test_api.py::test_get_incident_includes_rca_explanation_without_topology_fixture src/tests/test_api.py::test_get_rca_history_returns_evaluations_without_topology_fixture src/tests/test_api.py::test_get_rca_history_missing_incident_returns_404_without_topology_fixture
```

結果:

- 27 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、14-5 のRCA APIには影響しない。

### 14-6 検証結果

```bash
cd frontend && npm run build
```

結果:

- build passed
- Vite CJS Node API の非推奨警告とチャンクサイズ警告が出るが、ビルド自体は成功

### 14-7 検証結果

```bash
python -m pytest -q src/tests/test_ai_report.py::test_rca_explanation_included_in_prompt
```

結果:

- 1 passed
- 1 warning

14-7 の AI レポート全体と RCA 関連回帰として以下も確認した。

```bash
python -m pytest -q src/tests/test_ai_report.py src/tests/test_incident_store.py src/tests/test_root_cause.py::test_inferencer_attaches_rca_explanation_to_incident src/tests/test_root_cause.py::test_silent_root_rca_explanation_uses_topology_evidence src/tests/test_root_cause.py::test_rca_confidence_scores_topology_and_syslog_evidence src/tests/test_root_cause.py::test_silent_root_confidence_is_medium_but_not_zero
```

結果:

- 36 passed
- 1 warning

> warning は Starlette / httpx の非推奨互換警告で、14-7 のAI連携には影響しない。

### 14-8 検証結果

既存の `poc/topology/l3_topology.json` 依存を避けるため、テスト共通フィクスチャを5ノード/3エッジのインメモリトポロジーと一時YAMLへ置き換えた。

主要 API / Root Cause 回帰として以下を確認した。

```bash
python -m pytest -q src/tests/test_root_cause.py src/tests/test_api.py src/tests/test_api_ingest.py
```

結果:

- 56 passed
- 1 warning

Phase 14 全体の回帰として以下を確認した。

```bash
python -m pytest -q src/tests/test_root_cause.py src/tests/test_incident_store.py src/tests/test_api.py src/tests/test_ai_report.py
```

結果:

- 79 passed
- 1 warning

フロントエンド UI の回帰として以下も確認した。

```bash
cd frontend && npm run build
```

結果:

- build passed
- Vite CJS Node API の非推奨警告とチャンクサイズ警告が出るが、ビルド自体は成功

---

## Phase 15: 影響範囲算出 ⏳ 未着手

### 目的

トポロジーを持つ強みを活かし、根本原因ノードから見た業務影響を自動算出する。
単に「どの装置がログを出したか」ではなく、「どの拠点、VLAN、VRF、BGP peer、冗長経路、配下ノードに影響し得るか」を提示する。

### 影響範囲モデル案

```python
@dataclass
class ImpactScope:
  root_cause_node: str
  affected_nodes: list[str]
  affected_sites: list[str]
  affected_vlans: list[str]
  affected_vrfs: list[str]
  affected_bgp_peers: list[str]
  redundancy_status: str   # protected | degraded | isolated | unknown
  blast_radius_score: float
```

### 基本方針

1. `GraphEngine` にノード属性、リンク属性、レイヤー別依存関係を問い合わせる API を追加する。
2. root cause node の descendants と関連論理エッジから候補影響範囲を算出する。
3. 実際にログを出したノードと、トポロジー上影響し得るノードを区別する。
4. 冗長経路が残っている場合は `degraded`、到達経路が消えた場合は `isolated` とする。
5. UI では topology map と incident detail の両方で影響範囲を表示する。

### 実装タスク

| # | サブフェーズ | タスク | 対象ファイル | 状態 |
|---|---|---|---|---|
| 15-1 | A: 属性モデル | site、role、VLAN、VRF、interface、BGP peer、redundancy group の属性を整理する | `models.py`, `topology/yang_loader.py`, `configs/clos/yang_topology.yaml` | ⏳ |
| 15-2 | B: グラフ API | descendants、論理 peer、レイヤー依存、代替経路を取得するメソッドを追加する | `topology/graph_engine.py` | ⏳ |
| 15-3 | C: 影響算出器 | root cause と current condition から `ImpactScope` を生成する | `correlation/impact_analyzer.py` | ⏳ |
| 15-4 | D: 冗長性判定 | ECMP、MLAG、dual-homing、冗長 BGP peer を考慮して `protected/degraded/isolated` を判定する | `correlation/impact_analyzer.py`, `topology/` | ⏳ |
| 15-5 | E: 永続化/API | インシデントに impact scope を保存し、API で取得できるようにする | `persistence/incident_store.py`, `api/routes/incidents.py`, `api/schemas.py` | ⏳ |
| 15-6 | F: UI | IncidentCard と TopologyMap に影響範囲、blast radius、冗長性状態を表示する | `frontend/src/components/IncidentCard.tsx`, `frontend/src/components/TopologyMap.tsx` | ⏳ |
| 15-7 | G: AI/通知連携 | 通知と AI レポートに影響拠点、配下ノード数、冗長性状態を含める | `notification/`, `ai/report_generator.py` | ⏳ |
| 15-8 | H: テスト | 単一路、冗長路、BGP peer、VRF/VLAN、属性欠落時のフォールバックをテストする | `src/tests/test_root_cause.py`, `src/tests/test_yang_loader.py`, `src/tests/test_api.py` | ⏳ |

### テストシナリオ

| シナリオ | 期待結果 |
|---|---|
| Spine 障害で全 Leaf が配下にある | affected_nodes と affected_sites に配下機器・拠点が入る |
| dual-homed Leaf の片系 uplink 障害 | redundancy_status が `degraded` になる |
| 単一路 access switch の uplink 障害 | redundancy_status が `isolated` になる |
| BGP peer 障害 | affected_bgp_peers と関連 VRF が算出される |
| VLAN/VRF 属性が欠落している | `unknown` として扱い、影響算出全体は失敗しない |

### 完了条件

- [ ] インシデント作成・更新時に `ImpactScope` が生成される
- [ ] 影響を受けた実ログノードと、トポロジー上影響し得るノードを区別できる
- [ ] 拠点、VLAN、VRF、BGP peer の影響範囲を API で取得できる
- [ ] 冗長性状態を `protected/degraded/isolated/unknown` で表現できる
- [ ] 通知と AI レポートに影響範囲サマリを含められる
- [ ] TopologyMap で root cause、実影響、潜在影響を視覚的に区別できる

---

## Phase 16: 共有前の運用完成度向上 ✅

### 目的

他の利用者が Docker または開発環境で利用した際に、画面ごとの動作差、取込経路による相関結果の差、無認証の管理操作、再起動時の調査結果消失を避ける。
本フェーズでは新機能の追加より、既存機能を安全かつ一貫して利用できる状態にすることを優先する。

### 実装順序

先に配布済み UI の到達性を修正して基本操作を成立させ、その後に外部公開の安全性とデータ処理の一貫性を強化する。
認証方式は利用環境に依存するため、16-2 の着手時に要件を確定する。

| # | サブフェーズ | タスク | 対象ファイル | 状態 |
|---|---|---|---|---|
| 16-1 | A: UI/API 配布経路 | nginx と Vite proxy に `/filter`、`/raw-logs`、`/knowledge` を追加し、UI が利用する全 API と WebSocket が開発・Docker の両方で到達できるようにする。Compose の API 公開方針と `make docker-up` の案内も一致させる | `frontend/nginx.conf`, `frontend/vite.config.ts`, `docker-compose.yml`, `Makefile` | ✅ |
| 16-2 | B: 認証・認可 | 外部公開する REST API / WebSocket を認証し、閲覧、運用操作、破壊的操作、装置調査を権限で分離する。初期管理者とシークレットの設定方法を文書化する | `api/`, `frontend/`, `docker-compose.yml`, `README.md` | ✅ |
| 16-3 | C: 取込パイプライン統一 | `/ingest` を UDP 受信と同じ分類、相関・統合、復旧、メンテナンス、通知のパイプラインへ統合し、入力方式によってインシデント結果が変わらないようにする | `api/main.py`, `api/routes/ingest.py`, `ingestion/` | ✅ |
| 16-4 | D: CLI 通知修正 | ファイル・標準入力モードで `--vigil-url` を指定したときの未定義ロガー参照を修正し、通知有効時の一括・ストリーミング取込を回帰テストする | `__main__.py`, `tests/` | ✅ |
| 16-5 | E: 調査結果の永続化 | 調査の開始・進行・完了・失敗とコマンド結果を DB に保存し、再起動後も API / UI から確認できるようにする。実行中ジョブの再開可否と失敗時の扱いを明確にする | `investigation/`, `persistence/`, `api/routes/investigation.py`, `tests/` | ✅ |
| 16-6 | F: 配布検証・性能 | Docker Compose の起動試験、認証ありの主要 UI フロー、UDP と `/ingest` の等価性、再起動耐性を自動化する。フロントエンドは Cytoscape などを遅延ロードして初期チャンク警告を解消または許容根拠を記録する | `tests/`, `frontend/`, CI 設定 | ✅ |

### 判断基準

#### 16-1: UI/API 配布経路

- nginx の API proxy と Vite の開発 proxy が、UI クライアントの全 API パスを同じように転送する。
- API を外部公開しない場合、運用ドキュメントは UI 経由の利用方法だけを案内する。公開する場合は認証を必須とする。
- Docker 実行時に Raw Logs、Knowledge Review、フィルター再読込、インシデント、トポロジー、WebSocket 更新を確認する。

#### 16-2: 認証・認可

- 認証なしでは、ルール変更、トポロジー再読込、データ削除、インシデント解決、実機調査開始を実行できない。
- 読み取り専用利用者と運用管理者を分離する。削除と実機調査は明示的な管理権限を要求する。
- ローカル開発を阻害しないよう、開発専用の明示設定に限り認証を無効化できる。
- CORS は本番で UI の正規オリジンへ限定し、認証情報を含む場合の設定をテストする。

#### 16-3: 取込パイプライン統一

- 同じ SYSLOG 列を UDP と `POST /ingest` に与えた場合、保存されるインシデント、状態遷移、通知イベントが等価になる。
- `/ingest` のレスポンス仕様は、一括取込で新規作成・更新・復旧されたインシデントを利用者が判別できる形にする。互換性に影響する変更は API バージョンまたは移行案内を用意する。
- 処理共通化に伴う二重の Raw Log 保存、二重通知、同一バッチ内の順序不定を回帰テストする。

#### 16-4: CLI 通知修正

- `topology-syslog -i sample.log --vigil-url http://example.test` が `NameError` を起こさない。
- 通知失敗時も、ローカルの相関結果出力と終了コードの方針が一貫している。

#### 16-5: 調査結果の永続化

- 調査レポートとコマンド実行結果はプロセス再起動後も参照できる。
- 実行中の調査が再起動で中断された場合、状態を `failed` または `interrupted` として記録し、実行中のまま残さない。
- 機器コマンド出力に認証情報などの機微情報が含まれ得るため、16-2 の権限で保護する。

#### 16-6: 配布検証・性能

- Compose 起動から UI の主要画面と API 到達性を確認する結合テストを用意する。
- 認証なしアクセスの拒否、権限別の許可・拒否、破壊的操作の確認をテストする。
- フロントエンドの本番ビルドを CI で実行し、コード分割後に初期表示へ必要なチャンクサイズを記録する。

### 完了条件

- [x] 16-1: Docker と Vite 開発環境の両方で、UI が利用する全 API と WebSocket に到達できる
- [x] 16-2: 本番公開時、認証なしで管理・破壊的・実機調査操作を実行できない
- [x] 16-3: UDP と `/ingest` が同じ相関・復旧・通知パイプラインを通る
- [x] 16-4: `--vigil-url` 付き CLI 取込が正常に完了し、通知失敗時の動作もテストされている
- [x] 16-5: 調査レポートとコマンド結果が永続化され、再起動後も参照できる
- [x] 16-6: Compose 配布、認証、入力経路等価性、再起動耐性を含む結合テストが CI で実行される
- [x] Phase 16 の完了後、共有用の導入手順・運用手順・既知の制約を `README.md` に反映する
