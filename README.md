# topology-syslog

**トポロジー駆動型シスログサーバー** — ネットワークトポロジーを理解し、大量のアラートを根本原因単位のインシデントに自動集約する監視プラットフォーム。

---

## 概要

従来のシスログサーバーは、障害時に発生する大量のアラートをそのまま記録するだけです。例えばコアスイッチが1台ダウンすると、そこに繋がる数十台の機器が次々にアラートを送信し、運用者はアラートの洪水の中から真の原因を手作業で探さなければなりません。

**topology-syslog** は YANG モデルで定義されたネットワークトポロジーをインメモリグラフとして保持し、受信した SYSLOG をトポロジー構造にマッピングします。これにより「複数のSYSLOGメッセージ」を「1件の根本原因インシデント」に自動変換します。

```
従来:  障害1件 → アラート 87件 → 運用者が手作業でトリアージ

本システム:  障害1件 → アラート 87件 → 自動集約 → インシデント 1件（根本原因: Core-SW1）
```

---

## 主な機能

| 機能 | 説明 |
|---|---|
| SYSLOG 受信 | UDP (RFC 3164 / RFC 5424) 受信、`/ingest` API 経由での取り込み |
| **ファイル取り込み** | rsyslog が書き出したログファイルや `tail -f` パイプからインシデントへ変換 |
| **根本原因推論** | トポロジーグラフを用いた自動インシデント集約（後述） |
| BGP ピアリング対応 | iBGP など物理接続のない論理セッションもグラフエッジとして扱う |
| リアルタイム通知 | WebSocket でブラウザに即時プッシュ |
| REST API | インシデント CRUD、トポロジー参照・リロード |
| Web UI | React + Cytoscape.js によるトポロジービジュアライザー付きダッシュボード |
| **AI 障害レポート** | OpenAI / Ollama による障害分析レポート生成（RAG + キャッシュ対応） |
| **装置調査エージェント** | インシデント発生時に pyATS で実機 SSH 接続して状態収集。どの装置に何のコマンドを実行するかを LLM が自律判断 |
| YANG モデル | `iida-network-model` サブモジュールで物理・L2・L3・管理レイヤーを定義 |
| **メンテナンス計画** | 作業計画 YAML を読み込み、計画内機器からのインシデントを自動クローズ |

---

## インシデント集約の仕組み

このシステムの核となる部分です。

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

### 6. インシデントのステータスと現在状況

インシデントは **`status`**（ライフサイクル）と **`condition`**（ネットワーク現在状況）の 2 つの属性で管理されます。

#### `status` — オペレーターが管理するライフサイクル

| 値 | 意味 |
|---|---|
| `OPEN` | 受付中・未クローズ（新規生成時のデフォルト） |
| `CLOSED` | オペレーターが手動でクローズ済み |

#### `condition` — ネットワーク現在状況（システムが自動更新）

| 値 | 条件 |
|---|---|
| `ACTIVE` | 障害継続中（新規生成時のデフォルト） |
| `RECOVERED` | 復旧 SYSLOG を受信し、ネットワーク的に回復したと判断 |
| `FLAPPING` | 同一ノード × 同一イベントが 1 ウィンドウ内に N 回以上（デフォルト 3 回） |

> **設計の考え方**: 復旧イベントを受信してもインシデントは自動クローズしません。ネットワークが回復した事実を `condition = RECOVERED` として記録しつつ、インシデント自体は `status = OPEN` のまま残します。オペレーターが確認・対応を完了した後に `CLOSED` にします。

### 7. 自動復旧検知

> **注意**: 以下の動作は将来変更される可能性があります。

受信した SYSLOG に **復旧イベント** が含まれる場合、該当ノードを根本原因とする `OPEN` インシデントの `condition` を `RECOVERED` に更新します。
**インシデント自体はクローズされません**（`status` は `OPEN` のまま）。
復旧イベントは**新規インシデントを生成しません**。

**復旧イベントとみなすパターン:**

| パターン | 例 |
|---|---|
| `changed state to up` | `%LINK-3-UPDOWN: Interface Gi0/0, changed state to up` |
| `%BGP-x-ADJCHANGE: ... Up` | `%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Up` |
| `%OSPF-x-ADJCHG: ... to FULL` | `%OSPF-5-ADJCHG: Process 1, Nbr 10.0.0.2 to FULL` |
| `%ISIS-x-ADJCHANGE: ... UP` | IS-IS 隣接復旧 |
| `%SYS-x-RESTART` | システム再起動（復旧とみなす） |

**動作例:**

```
ウィンドウ1 (t=0-30s):
  Core-Router1: %LINK-3-UPDOWN: ... changed state to down
  Dist-SW1:     %LINEPROTO-5-UPDOWN: ... changed state to down
    → OPEN インシデント INC-xxxx-001 を生成（root_cause: Core-Router1, condition: ACTIVE）

ウィンドウ2 (t=30-60s):
  Core-Router1: %LINK-3-UPDOWN: ... changed state to up   ← 復旧イベント
    → 新規インシデントは生成しない
    → INC-xxxx-001 の condition を RECOVERED に更新（status は OPEN のまま）
    → WebSocket 経由でブラウザに即時反映
```

**現在の制約（将来変更の可能性あり）:**

- 復旧イベントを出したノードが根本原因（`root_cause_node`）のインシデントのみ `condition` を更新します。二次影響ノードが復旧しても、対応するインシデントの `condition` は変化しません。
- 復旧判定はパターンマッチング（正規表現）のみで行います。トポロジー情報（どのインターフェースが対応するか）は現在考慮していません。
- 同一ウィンドウ内にリンクダウンとリンクアップが混在する場合（高速フラッピング）、`condition = FLAPPING` のインシデントが生成されます。

### 8. メンテナンス計画による自動クローズ

ネットワーク保守作業中は、意図的な操作によって SYSLOG が発出されます。
`configs/maintenance/` に置いた作業計画 YAML を読み込み、計画の時間枠内・対象機器からのインシデントを自動的に `CLOSED` にします。

**動作フロー:**

```
ウィンドウ内の SYSLOG を処理
        │
        ▼
根本原因推論 → インシデント生成
        │
        ▼
  MaintenanceChecker.find_active_plan(incident)
  ├─ scheduled_start <= now <= scheduled_end
  ├─ status が planned または in-progress
  ├─ root_cause_node が affected-device のいずれかに該当（scope 考慮）
  └─ expected-syslog-pattern が指定されていれば primary_event と照合
        │
  該当あり ──► status=CLOSED / maintenance_plan_id=CHG-XXXX-NNNN をセットして保存
  該当なし ──► 通常通り status=OPEN で保存
```

**作業計画 YAML の書式（`configs/maintenance/CHG-YYYY-NNNN.yaml`）:**

```yaml
maintenance-plans:
  plan:
    - plan-id: "CHG-2026-0001"
      title: "Spine1 IOS-XE ファームウェアアップグレード"
      description: |
        install activate によるリロードが発生する。BGP セッション断あり。
      scheduled-start: "2026-08-25T02:00:00+09:00"  # RFC 3339 / ISO 8601
      scheduled-end:   "2026-08-25T04:00:00+09:00"
      status: planned   # planned | in-progress | completed | cancelled
      created-by: "iida"
      risk-level: high  # low | medium | high

      affected-device:
        - device-id: "Spine1"        # yang_topology.yaml の device-id と一致させる
          scope: including-links     # scope については下記参照
          note: "インプレースアップグレード。install activate でリロード。"
        - device-id: "Leaf1"
          scope: device-only
          note: "Spine1 向け eBGP セッション断 (ADJCHG) が発生する。"

      # 省略時 → 上記機器からのすべての SYSLOG を抑制
      # 指定時 → 1 件以上一致したものだけ抑制（Python 正規表現）
      expected-syslog-pattern:
        - '%LINK-3-UPDOWN'
        - '%BGP-5-ADJCHG'
```

**`scope` の意味:**

| 値 | 抑制対象 |
|---|---|
| `device-only` | その機器からのイベントのみ |
| `including-links` | その機器 ＋ 直接隣接ノード（リンクフラップが隣接装置にも波及する場合） |
| `including-downstream` | その機器 ＋ トポロジーグラフ上の全下流ノード（Spine 停止で Leaf が連鎖する場合） |

**`expected-syslog-pattern` の有無による動作の違い:**

| パターン指定 | 動作 |
|---|---|
| **省略** | 対象機器からのすべてのインシデントを自動クローズ |
| **指定あり** | `primary_event` がいずれかのパターンに一致するものだけクローズ。それ以外（例: CPU 警告）はインシデントとして残る |

**ホットリロード:**
ファイルの mtime を監視しており、変更を検知したタイムウィンドウのフラッシュ時に自動で再読み込みします。サーバーを再起動せずに計画の追加・修正が反映されます。

**インシデントの `maintenance_plan_id` フィールド:**
自動クローズされたインシデントには `maintenance_plan_id` に計画 ID（例: `CHG-2026-0001`）が記録されます。
API レスポンスや Web UI からクローズ理由を確認できます。

```json
{
  "incident_id": "INC-20260825-001",
  "status": "CLOSED",
  "maintenance_plan_id": "CHG-2026-0001",
  "root_cause_node": "Spine1"
}
```

**YANG モデル:**
作業計画のスキーマは `yang/iida-network-maintenance.yang` で定義されています。
`pyang -f tree yang/iida-network-maintenance.yang` でスキーマツリーを確認できます。

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
| `VIGIL_URL` | — | vigil の URL（設定するとインシデントを転送） |
| `VIGIL_TEAM` | `default` | vigil のチーム名 |
| `INVESTIGATION_ENABLED` | `false` | 装置調査エージェントの有効化 |
| `PYATS_TESTBED_FILE` | — | pyATS testbed YAML ファイルのパス（`INVESTIGATION_ENABLED=true` の場合必須） |
| `INVESTIGATION_MAX_TURNS` | `8` | LLM エージェントの最大ターン数 |
| `INVESTIGATION_COMMAND_TIMEOUT` | `30` | SSH コマンドタイムアウト（秒） |
| `MAINTENANCE_DIR` | — | 作業計画 YAML を置くディレクトリ（例: `configs/maintenance`） |

---

## 起動

### 開発モード（ローカル）

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

### Docker（本番 / 検証環境）

**前提**: Docker および Docker Compose v2 がインストール済みであること。

**1. `.env` を準備する**

```bash
cp .env.example .env
# AI レポートを使う場合は OPENAI_API_KEY などを編集
```

**2. ビルドして起動する**

```bash
make docker-up
# または
docker compose up --build -d
```

初回は Python パッケージ・npm ビルドのダウンロードが走るため数分かかります。

起動後:

- Web UI: http://localhost:3000
- API ドキュメント: http://localhost:8080/docs

**3. ログを確認する**

```bash
docker compose logs -f backend    # バックエンド
docker compose logs -f frontend   # nginx / フロントエンド
```

**4. 停止する**

```bash
make docker-down
# または
docker compose down
```

> データ（`incidents.db`、`.chromadb`）は Docker ボリューム `data` に保存されます。
> `docker compose down -v` を実行するとボリュームごと削除されます（復旧不可）。

**Syslog UDP ポートについて**

デフォルトでは `1514/udp` を公開しています。
実機や rsyslog から直接 `514/udp` で送信したい場合は `docker-compose.yml` の ports を変更してください:

```yaml
ports:
  - "514:1514/udp"   # ホストの 514 → コンテナの 1514
```

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

### デバイスごとの SYSLOG severity フィルター

デバイスに `syslog-min-severity` を設定すると、そのデバイスから受信した SYSLOG のうち、指定レベルより軽微なものを取り込み前に除外します。
重要度の高い装置（Spine など）はより詳細なログを収集し、末端装置はノイズを減らす、といった使い分けができます。

```yaml
    device:
      - device-id: "Spine1"
        role: spine
        syslog-min-severity: informational  # Informational (6) 以上の深刻度を受け入れる

      - device-id: "Leaf1"
        role: leaf
        syslog-min-severity: warning        # Warning (4) 以上のみ受け入れる（Notice/Info/Debug を捨てる）
```

| 設定値 | 受け入れる severity 番号 | 除外されるもの |
|---|---|---|
| `debug` (7) | 0〜7 | なし（**デフォルト・未設定時**） |
| `informational` (6) | 0〜6 | debug |
| `notice` (5) | 0〜5 | informational / debug |
| `warning` (4) | 0〜4 | notice / informational / debug |
| `error` (3) | 0〜3 | warning 以下すべて |
| `critical` (2) | 0〜2 | error 以下すべて |

整数値（`0`〜`7`）でも指定できます。`syslog-min-severity` を省略したデバイスはすべての severity を受け入れます。
`POST /topology/reload` でリロードすると設定は即時反映されます。

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
| `POST` | `/incidents/{id}/investigation` | 装置調査エージェントを起動（バックグラウンド実行） |
| `GET` | `/incidents/{id}/investigation` | 調査の進捗・結果を取得 |
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

**vigil AI エージェントとの役割分担**:

vigil と連携している場合、両 AI エージェントは以下のように役割を分担します。

| AI エージェント | 役割 | レポートの内容 | 読者 |
|---|---|---|---|
| **topology-syslog** | 「何が起きたか」 | 根本原因・影響ノード・生ログ解析・再発パターン・予防策 | ネットワークエンジニア |
| **vigil** | 「何をすべきか」 | 対応チェックリスト・確認コマンド・エスカレーション判断・顧客連絡文面 | オンコール担当者 |

vigil の `POST /api/v1/incidents/{id}/investigate` が呼び出された際、vigil は本エンドポイント（`POST /incidents/{id}/report`）を呼び出してレポートを取得し、それを技術的背景として行動指示レポートを生成します。topology-syslog 側の AI が無効の場合は、vigil が単独で汎用レポートを生成します。

---

## 装置調査エージェント

`INVESTIGATION_ENABLED=true` に設定すると、インシデントに対して実際のネットワーク装置に SSH 接続して状態情報を収集できます。

**特徴:**
- **LLM による自律的な調査計画**: どの装置に接続し、何のコマンドを実行するかを LLM が ReAct ループで自律判断する
- **pyATS による装置接続**: Cisco Systems が開発するネットワーク自動化フレームワーク pyATS (unicon) を使用。Cisco IOS / IOS-XE / IOS-XR / NX-OS などのマルチベンダー接続に対応
- **Genie パーサー**: `show ip bgp summary` などの主要コマンドは Genie が構造化データ（Python dict）に自動変換。LLM が解析しやすい形式で提供される
- **read-only 制御**: `show` / `display` コマンドのみ許可。設定変更コマンドは実行不可

### 動作の流れ

```
POST /incidents/{id}/investigation
        │
        ▼  バックグラウンドタスクとして起動（即 202 返却）
        │
        ▼
LLM エージェント（ReAct ループ、最大 8 ターン）
  ┌─────────────────────────────────────────────────────┐
  │ Turn 1: インシデントを分析 → get_topology_info("Spine1") を呼び出す    │
  │ Turn 2: Spine1 の役割・隣接情報を受け取る                              │
  │         → run_commands("Spine1", ["show ip bgp summary", ...]) を呼ぶ │
  │ Turn 3: コマンド出力を受け取り、必要なら隣接装置も調査                 │
  │ Turn 4: 収集情報をもとに最終レポートを生成（finish）                   │
  └─────────────────────────────────────────────────────┘
        │
        ▼
InvestigationReport を保存 + WebSocket で investigation.done を配信
```

### セットアップ

**1. pyATS をインストールする**

```bash
uv sync   # pyproject.toml に pyats・genie が含まれているため自動インストール
```

**2. pyATS testbed YAML を用意する**

接続情報は pyATS 標準の testbed YAML ファイルで管理します。
`configs/clos/testbed.yaml` がラボ環境（CML）向けのサンプルとして同梱されています。

```yaml
# configs/clos/testbed.yaml
testbed:
  name: agentic-ni-clos
  credentials:
    default:
      username: cisco
      password: cisco     # 本番では %ENV{DEVICE_PASSWORD} 等で環境変数化
    enable:
      password: cisco

devices:
  Spine1:
    os: iosv
    type: router
    connections:
      cli:
        protocol: ssh
        ip: 10.0.0.1      # Loopback0（Ubuntu から BGP ファブリック経由で到達）
        port: 22
  # Spine2 / Leaf1 / Leaf2 / Leaf3 も同様
```

```bash
export PYATS_TESTBED_FILE=configs/clos/testbed.yaml
```

**3. 有効化して起動する**

```bash
INVESTIGATION_ENABLED=true \
PYATS_TESTBED_FILE=configs/clos/testbed.yaml \
topology-syslog
```

### 使い方

```bash
# 調査を開始する（バックグラウンド実行）
curl -X POST http://localhost:8080/incidents/INC-20260820-001/investigation

# 結果を確認する
curl http://localhost:8080/incidents/INC-20260820-001/investigation
```

```json
{
  "incident_id": "INC-20260820-001",
  "status": "completed",
  "summary": "Spine1 の GigabitEthernet0/0 がダウンし、接続する Leaf1-3 の BGP セッションが全断しました。\n\n**推奨対応**: ...",
  "commands": [
    {
      "device_id": "Spine1",
      "command": "show ip bgp summary",
      "output": "BGP router identifier 10.0.0.1, ...",
      "timestamp": "2026-08-20T10:00:15Z",
      "error": null
    }
  ]
}
```

WebSocket でリアルタイムに調査完了を受け取ることもできます。

```json
// /ws/incidents からの通知
{"type": "investigation.done", "incident_id": "INC-20260820-001", "status": "completed"}
```


<br><br>

---

<br><br>

## vigil 連携

[vigil](https://github.com/your-org/vigil) はインシデント管理・エスカレーション通知プラットフォームです。

topology-syslog が生成したインシデントを vigil に転送することで、オンコール担当者への通知・エスカレーション・クローズ管理を vigil 側で一元管理できます。

### 動作の流れ

```
ネットワーク機器
     │  SYSLOG (UDP)
     ▼
topology-syslog
  ├─ 根本原因推論 → インシデント生成
  ├─ DB 保存 / WebSocket 配信
  └─ POST /api/v1/alerts  ──► vigil
                                  ├─ 重複排除（fingerprint）
                                  ├─ オンコール担当者へ通知
                                  └─ エスカレーションポリシー適用
```

### 設定

`.env` に以下を追加するだけで有効になります。

```bash
VIGIL_URL=http://vigil:8000   # vigil サーバーの URL
VIGIL_TEAM=network            # 通知先チーム（vigil のスケジュールと対応）
```

`VIGIL_URL` が未設定の場合、vigil 転送は無効です（他の機能には影響しません）。

### 優先度マッピング

topology-syslog のインシデントは vigil の優先度（P1〜P4）に以下のルールで変換されます。

| 条件 | vigil 優先度 |
|---|---|
| ステータスが `FLAPPING` | `P2` |
| 同一根本原因ノードで `OPEN` のインシデントが既に存在する（`recurrence_count > 0`） | `P2` |
| それ以外 | `P3`（デフォルト） |

> **`recurrence_count` の計算**: 新規インシデントを保存する直前に、同じ根本原因ノードを持つ **`status = OPEN`** のインシデント件数をカウントします。`CLOSED` になったインシデント（メンテナンス自動クローズ・手動クローズ含む）はカウント対象外です。

### vigil 側の重複排除

vigil は `source`（根本原因ノード名）と `title` から fingerprint を計算し、同一インシデントの重複登録を防ぎます。
topology-syslog の同一インシデントが複数回転送されても、vigil 側では 1 件として扱われます。

### インシデントのライフサイクル

topology-syslog と vigil はそれぞれ独立してインシデントを管理しますが、以下のタイミングで双方向に同期します。

| 操作 | topology-syslog | vigil |
|---|---|---|
| 障害 SYSLOG 受信 | `OPEN` インシデントを生成 | `POST /api/v1/alerts` を受信して triggered |
| 復旧 SYSLOG 受信 | 自動 `RESOLVED` → **vigil も自動 resolve**（連動） | resolved |
| topology-syslog で手動 resolve | `RESOLVED` | **同 source の vigil インシデントも resolve**（連動） |
| vigil で手動 Resolve | **topology-syslog インシデントも resolve**（連動） | resolved |

### Docker Compose での構成例

```yaml
services:
  topology-syslog:
    build: .
    environment:
      - VIGIL_URL=http://vigil:8000
      - VIGIL_TEAM=network
    depends_on:
      - vigil

  vigil:
    image: vigil:latest
    ports:
      - "8000:8000"
```

---

## SYSLOG ファイル取り込みモード

APIサーバーを起動せずに、rsyslog が書き出したログファイルや `tail -f` パイプから直接インシデントへ変換できます。

### ファイルを一括処理する

```bash
topology-syslog -i network-syslog.txt -t configs/clos/yang_topology.yaml
```

ログのタイムスタンプをもとに `WINDOW_SEC`（デフォルト 30 秒）ごとのウィンドウへ自動グループ化し、根本原因推論を実行します。

### パイプ（ストリーミング）で受け取る

```bash
tail -f /var/log/network-syslog.txt | topology-syslog -i
```

`tail -f` から流れてくる行を逐次パースし、`WINDOW_SEC` 秒間新規行が来なければバッファをフラッシュして推論します。EOF でも残バッファを処理します。

### オプション

| オプション | 説明 |
|---|---|
| `-i [FILE]` | ファイル指定（省略時は標準入力） |
| `-t FILE` / `TOPOLOGY_PATH` | トポロジー定義ファイル（**必須**） |
| `--json` | インシデントを JSON Lines 形式で出力 |
| `--vigil-url URL` / `VIGIL_URL` | vigil の URL（設定するとインシデントを vigil へ直接転送） |
| `--vigil-team TEAM` / `VIGIL_TEAM` | vigil のチーム名（デフォルト `default`） |
| `TOPOLOGY_SOURCE` | トポロジー形式（`iida-yaml` / `ietf-json`） |
| `WINDOW_SEC` | タイムウィンドウ秒数（デフォルト `30`） |
| `DATABASE_URL` | 指定するとインシデントを DB にも保存 |
| `SYSLOG_IGNORE_FILE` | 無視パターンファイル |
| `MAINTENANCE_DIR` | 作業計画 YAML のディレクトリ。ログのタイムスタンプ基準で判定するため、過去ログ処理でも正しい時間帯でメンテナンス抑制が適用される |

### vigil への転送（ファイル取り込み時）

`--vigil-url`（または `VIGIL_URL` 環境変数）を指定すると、ファイル／ストリームから変換したインシデントを vigil の `POST /api/v1/alerts` へリアルタイムに転送します。

```bash
# 過去ログを一括処理して vigil に取り込む
topology-syslog -i network-syslog.txt \
  -t configs/clos/yang_topology.yaml \
  --vigil-url http://vigil:8000 \
  --vigil-team network

# tail -f パイプで vigil にリアルタイム転送する
tail -f /var/log/network-syslog.txt | \
  VIGIL_URL=http://vigil:8000 VIGIL_TEAM=network \
  topology-syslog -i -t configs/clos/yang_topology.yaml
```

JSON Lines 出力と組み合わせることも可能です（stdout に JSON を出しつつ vigil にも転送）:

```bash
topology-syslog -i syslog.txt -t topology.yaml --json --vigil-url http://vigil:8000 | jq .
```

転送に失敗した場合はログに警告を出力し、処理を継続します。vigil が起動していない場合でも SYSLOG の変換自体は正常に完了します。

### 出力例

```
[INCIDENT] INC-20260817-001
  Root Cause  : Spine1
  Event       : (inferred — node did not send SYSLOG)
  Secondary   : Leaf1, Leaf2, Leaf3
  Logs        : 4
  Status      : OPEN

1 incident(s) found.
```

`--json` を指定すると JSON Lines 形式で出力されます（ログ分析ツールへのパイプに便利です）:

```bash
tail -f /var/log/network-syslog.txt | topology-syslog -i --json | jq .
```

```json
{"incident_id": "INC-20260817-001", "root_cause_node": "Spine1", "secondary_nodes": ["Leaf1", "Leaf2", "Leaf3"], "raw_log_count": 4, "status": "OPEN", ...}
```

### rsyslog との連携例

rsyslog でネットワーク機器のログをファイルに記録している場合:

```bash
# /etc/rsyslog.d/10-network.conf
:fromhost-ip, startswith, "10." /var/log/network-syslog.txt
```

その後、以下のように取り込みます:

```bash
# 既存ファイルを一括処理（過去ログの分析）
export TOPOLOGY_PATH=/etc/topology-syslog/yang_topology.yaml
topology-syslog -i /var/log/network-syslog.txt

# リアルタイムで監視
tail -f /var/log/network-syslog.txt | topology-syslog -i
```

#### Mac で rsyslog がすでに 514/udp を使用している場合

Mac の rsyslog が `514/udp` を占有している場合は、topology-syslog をデフォルトの `1514/udp` のまま起動し、rsyslog に転送ルールを追加することで共存できます。

```
ネットワーク機器 → rsyslog (:514) → ファイル保存 + topology-syslog (:1514) へ転送
```

`/opt/homebrew/etc/rsyslog.conf` に転送ルールを追加します:

```conf
# ネットワーク機器 (10.x.x.x) のログをファイルに保存
:fromhost-ip, startswith, "10." /var/log/network-syslog.txt

# 同じログを topology-syslog（1514/udp）にも転送（@ = UDP、@@ = TCP）
:fromhost-ip, startswith, "10." @127.0.0.1:1514
```

`docker-compose.yml` はデフォルトの `1514:1514/udp` のまま変更不要です。

ポート競合を完全に避けたい場合は、`tail -f` によるファイル取り込みモードも利用できます:

```bash
tail -f /var/log/network-syslog.txt | topology-syslog -i
```

<br><br>

---

<br><br>

## 長期稼働に関する注意事項

### Docker ログローテーション

`docker-compose.yml` に `json-file` ドライバの `max-size` / `max-file` を設定しています。

| コンテナ | 最大サイズ | 保持ファイル数 | 最大合計 |
|---|---|---|---|
| backend | 20 MB | 5 | 100 MB |
| frontend | 10 MB | 3 | 30 MB |

### インシデントの自動アーカイブ

`RESOLVED` かつ作成から **90 日以上**経過したインシデントは、サーバー起動から 24 時間後に初回削除され、以後 24 時間ごとに自動実行されます。
`OPEN` / `FLAPPING` のインシデントは削除されません。

### SYSLOG ログの保存上限

1 件のインシデントに対して DB に保存する生ログは最大 **200 件**までです。
200 件を超えた分は削捨されますが、`raw_log_count` には実際の受信件数が正確に記録されます。

### AI クエリキャッシュの自動クリーンアップ

AI レポートの結果をキャッシュする `ai_cache` テーブルは、TTL (`AI_CACHE_TTL_DAYS`、デフォルト 7 日) 切れの行を 24 時間ごとに自動削除します。

### RAG ストア（ChromaDB）

ChromaDB は自動プルーニングされません。Docker 環境ではボリューム `data` 内の `/data/.chromadb` に保存されます。
ディスク使用量が問題になる場合は、コンテナを停止して手動で削除してください。

```bash
# Docker 環境で ChromaDB をリセットする場合
docker compose down
rm -rf data/.chromadb
docker compose up -d
```

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
│   ├── clos/
│   │   ├── yang_topology.yaml  # トポロジー定義（編集してください）
│   │   └── syslog_ignore.txt   # 無視パターン一覧
│   └── maintenance/            # 作業計画 YAML（MAINTENANCE_DIR 環境変数で指定）
│       └── CHG-YYYY-NNNN.yaml  # 1 ファイル = 1 変更申請（複数計画の定義も可）
├── yang/                       # YANG モデル
│   ├── iida-network-model.yang          # ネットワーク構成モデル（メインモジュール）
│   └── iida-network-maintenance.yang    # 作業計画モデル
├── src/
│   └── topology_syslog/
│       ├── ingestion/          # SYSLOG 受信・パース・フィルター
│       ├── topology/           # YANG → NetworkX グラフ変換
│       ├── correlation/        # タイムウィンドウ + 根本原因推論
│       ├── persistence/        # インシデント DB（SQLite / PostgreSQL）
│       ├── maintenance/        # 作業計画ローダー・自動クローズ判定
│       ├── notification/       # Webhook / Slack 通知
│       ├── ai/                 # LLM クライアント / キャッシュ / RAG / レポート生成
│       ├── investigation/      # 装置調査エージェント（pyATS + LLM ReAct ループ）
│       └── api/                # FastAPI アプリ・ルーター
└── frontend/                   # React + Vite + Tailwind CSS + Cytoscape.js
```
