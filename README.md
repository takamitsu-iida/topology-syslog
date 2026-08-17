# topology-syslog

**トポロジー駆動型シスログサーバー** — ネットワークトポロジーを理解し、大量のアラートを根本原因単位のインシデントに自動集約する監視プラットフォーム。

---

## 概要

従来のシスログサーバーは、障害時に発生する大量のアラートをそのまま記録するだけです。例えばコアスイッチが1台ダウンすると、そこに繋がる数十台の機器が次々にアラートを送信し、運用者はアラートの洪水の中から真の原因を手作業で探さなければなりません。

**topology-syslog** は YANG モデルで定義されたネットワークトポロジーをインメモリグラフとして保持し、受信した SYSLOG をトポロジー構造にマッピングします。これにより「数百件のアラート」を「1件の根本原因インシデント」に自動変換します。

```
従来:  障害1件 → アラート 87件 → 運用者が手作業でトリアージ

本システム:  障害1件 → アラート 87件 → 自動集約 → インシデント 1件（根本原因: Core-SW1）
```

---

## 主な機能

| 機能 | 説明 |
|---|---|
| SYSLOG 受信 | UDP (RFC 3164 / RFC 5424) 受信、`/ingest` API 経由での取り込み |
| **根本原因推論** | トポロジーグラフを用いた自動インシデント集約（後述） |
| BGP ピアリング対応 | iBGP など物理接続のない論理セッションもグラフエッジとして扱う |
| リアルタイム通知 | WebSocket でブラウザに即時プッシュ |
| REST API | インシデント CRUD、トポロジー参照・リロード |
| Web UI | React + Cytoscape.js によるトポロジービジュアライザー付きダッシュボード |
| **AI 障害レポート** | OpenAI / Ollama による障害分析レポート生成（RAG + キャッシュ対応） |
| YANG モデル | `iida-network-model` サブモジュールで物理・L2・L3・管理レイヤーを定義 |

---

## インシデント集約の仕組み

ここがこのシステムの核心です。

### 1. タイムウィンドウバッファ

受信した SYSLOG はすぐに処理されず、**スライディングウィンドウ**（デフォルト 30 秒）に蓄積されます。
最初のメッセージが到着してから 30 秒後に、ウィンドウ内の全メッセージをまとめて処理します。

```
t=0s  Spine1: %LINK-3-UPDOWN ─┐
t=1s  Leaf1:  %BGP-5-ADJCHANGE │ ← 30秒間バッファに溜める
t=2s  Leaf2:  %BGP-5-ADJCHANGE │
t=3s  Leaf3:  %BGP-5-ADJCHANGE ─┘
                                ▼ (t=30s) まとめて根本原因推論
```

### 2. トポロジーグラフの構築

`yang_topology.yaml` に定義されたトポロジーを有向グラフ（DAG）として保持します。
エッジの向きは「上流 → 下流」です。上流ノードが障害を起こすと下流が影響を受ける、という方向を表します。

```
          Spine1 ──── Spine2
         / │           │ \
     Leaf1 Leaf2    Leaf2  Leaf3
```

有向グラフとして表現すると:

```
Spine1 ──► Leaf1
Spine1 ──► Leaf2
Spine1 ──► Leaf3
Spine2 ──► Leaf1
Spine2 ──► Leaf2
Spine2 ──► Leaf3
Leaf1  ···► Leaf2  (BGP iBGP セッション、破線)
Leaf1  ···► Leaf3  (BGP iBGP セッション、破線)
Leaf2  ···► Leaf3  (BGP iBGP セッション、破線)
```

ノードの役割（`spine`, `leaf` など）に基づき優先度を付け、優先度が高い（上流の）ノードから低い（下流の）ノードへエッジを張ります。

### 3. 根本原因推論アルゴリズム

ウィンドウ内の SYSLOG を送信したノード群（`logged_nodes`）に対して推論を行います。

**ステップ 1: 根本原因候補の特定**

`logged_nodes` の中で、「自身より上流のノードが同じウィンドウ内でログを出していない」ノードを根本原因とみなします。

```python
root_causes = [
    n for n in logged_nodes
    if not ancestors(n) ∩ logged_nodes
]
```

**ステップ 2: 二次影響ノードの特定**

根本原因ノードの子孫（`descendants`）の中で、同じウィンドウ内でログを出しているノードを二次影響ノードとします。

```python
secondary = descendants(root_cause) ∩ logged_nodes
```

**ステップ 3: インシデント生成**

根本原因ノード + 二次影響ノード + 関連ログをまとめて 1 件のインシデントとして記録します。

### 4. 具体例

**例 A: Spine1 障害による連鎖**

```
ウィンドウ内のログ:
  Spine1: "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"
  Leaf1:  "%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down"
  Leaf2:  "%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down"
  Leaf3:  "%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down"

推論:
  Spine1 の ancestors ∩ logged_nodes = {} → 根本原因
  Spine1 の descendants = {Leaf1, Leaf2, Leaf3}
  secondary = {Leaf1, Leaf2, Leaf3}

結果: インシデント 1件
  root_cause_node: "Spine1"
  secondary_nodes: ["Leaf1", "Leaf2", "Leaf3"]
  raw_log_count:   4
```

**例 B: 独立した2拠点の障害**

```
ウィンドウ内のログ:
  Spine1: "%LINK-3-UPDOWN: ... down"
  Leaf1:  "%BGP-5-ADJCHANGE: ... Down"
  Spine2: "%LINK-3-UPDOWN: ... down"   ← 独立した障害
  Leaf2:  "%BGP-5-ADJCHANGE: ... Down"

推論:
  Spine1 → root cause (Leaf1 は secondary)
  Spine2 → root cause (Leaf2 は secondary)

結果: インシデント 2件
  INC-1: root_cause="Spine1", secondary=["Leaf1"]
  INC-2: root_cause="Spine2", secondary=["Leaf2"]
```

**例 C: iBGP セッション障害（BGP エッジの活用）**

```
ウィンドウ内のログ:
  Leaf1: "%BGP-5-ADJCHANGE: neighbor 10.0.0.12 Down"  ← BGP イベント
  Leaf2: "%BGP-5-ADJCHANGE: neighbor 10.0.0.11 Down"  ← BGP イベント

BGP エッジ: Leaf1 ──► Leaf2 (iBGP)

推論:
  Leaf2 の ancestors via BGP = {Leaf1}  → Leaf1 が根本原因
  secondary = {Leaf2}

結果: インシデント 1件
  root_cause_node: "Leaf1"
  secondary_nodes: ["Leaf2"]
```

### 5. BGP エッジの有効化ルール

BGP エッジ（物理接続を持たない論理ピアリング）は、宛先ノードが **BGP/ルーティングプロトコル関連の SYSLOG** を出している場合のみ集約に使われます。
無関係な SYSLOG（設定変更通知など）では BGP エッジを無視し、誤集約を防ぎます。

| 宛先ノードのログ | BGP エッジ | 集約 |
|---|---|---|
| `%BGP-5-ADJCHANGE` など | **有効** | iBGP 経由で同一インシデントに集約 |
| `%SYS-5-CONFIG_I` など | **無効** | 独立インシデントとして生成 |

---

## セットアップ

### 前提条件

- Python 3.12 以上
- Node.js 18 以上（フロントエンド用）
- `npm`

### 初回セットアップ

```bash
git clone https://github.com/your-org/topology-syslog.git
cd topology-syslog
make setup
```

`make setup` は以下を自動実行します:

1. `uv` が未インストールであればインストール
2. `yang/` サブモジュール（YANG モデル定義）を取得
3. `uv sync` で Python 依存パッケージをインストール
4. `cd frontend && npm install` でフロントエンド依存パッケージをインストール

---

## 設定

プロジェクトルートに `.env` ファイルを作成します（`.env.example` を参考にしてください）。

```bash
cp .env.example .env
```

AIによるレポート生成やCMLを使った検証環境を作成するには `.env` ファイルに環境変数を記載してください。

### 主な環境変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `TOPOLOGY_PATH` | — | トポロジー定義 YAML のパス（必須） |
| `TOPOLOGY_SOURCE` | `iida-yaml` | トポロジー形式（`iida-yaml` / `ietf-json`） |
| `SYSLOG_IGNORE_FILE` | — | 無視パターンファイルのパス |
| `API_PORT` | `8080` | バックエンド API のポート |
| `SYSLOG_PORT` | `1514` | SYSLOG UDP 受信ポート |
| `WINDOW_SEC` | `30` | タイムウィンドウ（秒） |
| `DATABASE_URL` | `sqlite:///./incidents.db` | インシデント DB の接続先 |
| `AI_ENABLED` | `false` | AI レポート機能の有効化 |
| `LLM_PROVIDER` | `openai` | LLM プロバイダー（`openai` / `ollama`） |
| `OPENAI_API_KEY` | — | OpenAI API キー（`AI_ENABLED=true` の場合必要） |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama のベース URL |
| `OLLAMA_MODEL` | `llama3` | Ollama のモデル名 |

---

## 起動

```bash
make start        # バックエンド + フロントエンドを同時起動

make stop         # 停止
make restart      # 再起動
make status       # プロセス状態確認
make logs-api     # バックエンドログを tail -f
make logs-ui      # フロントエンドログを tail -f
```

起動後:

- Web UI: http://localhost:3000
- API ドキュメント: http://localhost:8080/docs

---

## トポロジー定義

`configs/clos/yang_topology.yaml` でネットワーク構成を定義します。

### デバイスと物理接続

```yaml
network-model:
  physical-layer:
    device:
      - device-id: "Spine1"
        role: spine          # spine / leaf / core / distribution / access
        loopback: "10.0.0.1/32"
        interface:
          - interface-id: "GigabitEthernet0/0"
            ip-address: "10.1.11.1/30"

    physical-connection:
      - connection-id: "Spine1-Leaf1"
        endpoint:
          - device-id: "Spine1"
            interface-id: "GigabitEthernet0/0"
          - device-id: "Leaf1"
            interface-id: "GigabitEthernet0/0"
```

### BGP セッション（物理接続のない論理ピアリング）

```yaml
  layer3-layer:
    bgp-session:
      - session-id: "Leaf1-Leaf2-iBGP"
        type: ibgp            # ibgp / ebgp
        endpoint:
          - device-id: "Leaf1"
          - device-id: "Leaf2"
```

> **ホスト名の一致**: デバイスの `device-id` は、Cisco IOS の `hostname` コマンドおよび
> `logging origin-id hostname` で送信されるホスト名と一致させてください。

---

## API リファレンス

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/incidents` | インシデント一覧（`?status=OPEN` でフィルタ可） |
| `GET` | `/incidents/{id}` | インシデント詳細 |
| `PUT` | `/incidents/{id}/resolve` | インシデントをクローズ |
| `POST` | `/incidents/{id}/report` | AI 障害レポートを生成（キャッシュあり） |
| `GET` | `/topology/nodes` | グラフのノード一覧 |
| `GET` | `/topology/graph` | グラフ全体（Cytoscape.js 形式） |
| `POST` | `/topology/reload` | トポロジーをファイルから再読み込み |
| `POST` | `/ingest` | SYSLOG メッセージを直接投入（Vector 連携用） |
| `GET` | `/debug/status` | パイプライン状態確認 |
| `WS` | `/ws` | リアルタイムインシデント通知 |

---

## AI 障害レポート機能

`AI_ENABLED=true` に設定すると、インシデント詳細画面に「AI レポートを生成」ボタンが表示されます。

**動作の流れ:**

```
インシデント詳細を開く
        │
        ▼
「AI レポートを生成」ボタンをクリック
        │
        ▼
QueryCache 確認 ── HIT → キャッシュ済みレポートを即返却
        │
       MISS
        ▼
RAGStore で過去の類似インシデントを検索（ChromaDB）
        │
        ▼
LLM へプロンプト送信（インシデント概要 + 類似事例）
        │
        ▼
レポートをキャッシュ保存 + RAGStore へ追加
        │
        ▼
画面に Markdown レポートを表示
```

**キャッシュキー**: 根本原因ノード + Cisco IOS イベント種別（`%FAC-SEV-MNEM`）+ 二次影響ノード集合のハッシュ。
同じ種別の障害が再発した場合、LLM への問い合わせをスキップして即返却します。

**RAG（蓄積型学習）**: 生成したレポートは ChromaDB に蓄積され、次回の類似インシデント分析時の参考情報として使われます。インシデントが蓄積されるほど、レポートの精度が向上します。

---

## テスト

```bash
make test
# または
uv run python -m pytest src/tests/ -v
```

---

## ディレクトリ構造

```
topology-syslog/
├── Makefile                    # start / stop / setup / test
├── pyproject.toml
├── configs/
│   └── clos/
│       ├── yang_topology.yaml  # トポロジー定義（編集してください）
│       └── syslog_ignore.txt   # 無視パターン一覧
├── yang/                       # iida-network-model YANG モデル（サブモジュール）
├── src/
│   └── topology_syslog/
│       ├── ingestion/          # SYSLOG 受信・パース・フィルター
│       ├── topology/           # YANG → NetworkX グラフ変換
│       ├── correlation/        # タイムウィンドウ + 根本原因推論
│       ├── persistence/        # インシデント DB（SQLite / PostgreSQL）
│       ├── notification/       # Webhook / Slack 通知
│       ├── ai/                 # LLM クライアント / キャッシュ / RAG / レポート生成
│       └── api/                # FastAPI アプリ・ルーター
└── frontend/                   # React + Vite + Tailwind CSS + Cytoscape.js
```
