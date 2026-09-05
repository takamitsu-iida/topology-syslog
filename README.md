# topology-syslog

**Topology-aware SYSLOG RCA server** - ネットワークトポロジーを事前ロードし、多数の SYSLOG から根本原因候補を推定してインシデントを生成する監視プラットフォームです。

現在の標準エンジンは **Hypothesis-Based RCA** です。`make start`、Docker Compose、通常の `/ingest` は新方式で動作します。旧方式は `RCA_ENGINE=legacy` を明示した場合の rollback 用としてのみ残しています。

---

## 概要

従来の SYSLOG サーバーはログを保存するだけで、障害がどこから波及したかを理解できません。たとえば 1 本の物理リンク断や 1 台の Spine 障害から、複数装置の BGP down、interface down、到達性エラーが連鎖しても、運用者は大量のログから原因を探す必要があります。

topology-syslog は、YANG 形式のトポロジーを原因推論用グラフとしてロードし、SYSLOG を観測事実 `Observation` に正規化します。その後、根本原因候補 `Hypothesis` を採点し、最も説明力の高い候補を `Incident` に投影します。

```text
Raw SYSLOG
  -> Parser
  -> SKB / Severity Classification
  -> Observation
  -> ObservationBuffer
  -> HypothesisScorer
  -> RCAResult
  -> IncidentProjector
  -> Store / Notification / UI
```

この方式では、根本原因を装置単位だけでなく、`Device` / `Interface` / `PhysicalLink` / `BGPSession` として扱います。リンク障害、装置障害、単体インターフェース障害、BGP セッション障害、サイレント障害、復旧イベントを同じ枠組みで評価できます。

---

## 主な機能

| 機能 | 説明 |
|---|---|
| SYSLOG 受信 | UDP 受信、`/ingest` API、ファイル/標準入力取り込みに対応 |
| Hypothesis-Based RCA | Observation 群から root cause object を推定し、score / confidence / 根拠を保存 |
| Causal Topology | Device / Interface / PhysicalLink / BGPSession を原因候補としてグラフ化 |
| SYSLOG Knowledge Base | SKB と Severity policy により `fault-signal` / `state-change` / `recovery` / `retain-only` へ分類 |
| Observation Buffer | event time ベースの短時間 window で遅延到着ログを扱い、RCA 改訂を可能にする |
| Incident Projection | `RCAResult` を既存 `Incident` モデルへ投影し、API/UI/通知へ接続 |
| 復旧 Lifecycle | recovery Observation により `RECOVERING` / `RECOVERED` / `FLAPPING` を更新 |
| 比較・移行 API | legacy / hypothesis の差分確認、ラベル付きサンプルによる移行評価 |
| Web UI | React + Cytoscape.js によるインシデント、トポロジー、RCA 根拠表示 |
| AI 障害レポート | OpenAI / Ollama による RCA 根拠付き障害レポート生成 |
| 装置調査エージェント | pyATS + LLM による実機調査支援 |
| メンテナンス計画 | 作業計画 YAML と照合し、計画内インシデントを自動クローズ |

---

## 起動

### ローカル開発

```bash
make setup
make start
```

`make start` は次を起動します。

| サービス | URL |
|---|---|
| Web UI | http://localhost:3000 |
| API | http://localhost:8080 |
| Node Monitor | http://localhost:8090 |

デフォルトでは以下の設定で起動します。

```text
TOPOLOGY_PATH=configs/clos/yang_topology.yaml
TOPOLOGY_SOURCE=iida-yaml
RCA_ENGINE=hypothesis
SYSLOG_PORT=1514
```

操作コマンド:

```bash
make stop
make restart
make status
make logs-api
make logs-ui
make logs-monitor
```

### Docker Compose

```bash
cp .env.example .env
make docker-up
```

Docker Compose でも backend は `RCA_ENGINE=hypothesis` で起動します。Compose では認証が有効です。`.env` にトークンを設定してください。

```bash
AUTH_ADMIN_TOKEN="replace-with-a-long-random-secret"
AUTH_READER_TOKEN="replace-with-reader-secret"
AUTH_OPERATOR_TOKEN="replace-with-operator-secret"
NODE_MONITOR_EVENT_TOKEN="replace-with-node-event-secret"
NODE_MONITOR_API_TOKEN="replace-with-node-api-secret"
```

停止:

```bash
make docker-down
```

データは Docker volume `data` に保存されます。`docker compose down -v` は DB と RAG データを削除します。

---

## RCA エンジン

### 標準: hypothesis

`hypothesis` は現在の標準エンジンです。通常の `/ingest` と UDP 受信はこの経路でインシデントを保存・通知します。

```bash
RCA_ENGINE=hypothesis make restart
```

### 比較: dual

`dual` は legacy と hypothesis を同じ SYSLOG で比較します。通常の保存・通知は legacy 側を使い、hypothesis の結果は debug API で確認します。

```bash
RCA_ENGINE=dual make restart
```

### rollback: legacy

旧方式に戻す場合だけ明示します。

```bash
RCA_ENGINE=legacy make restart
```

旧方式は保守・切戻し用途です。新規改善の主対象は hypothesis 側です。

---

## Hypothesis-Based RCA の仕組み

### 1. Causal Object

トポロジーから原因候補になり得る object を作成します。

| Object | 例 | 用途 |
|---|---|---|
| `Device` | `Device:Spine1` | 装置停止、サイレント障害 |
| `Interface` | `Interface:Leaf1:GigabitEthernet0/0` | 単体インターフェース障害 |
| `PhysicalLink` | `PhysicalLink:Leaf1:Gi0/0--Spine1:Gi0/0` | 両端 IF / BGP 断をまとめる物理リンク障害 |
| `BGPSession` | `BGPSession:Spine1-Leaf1-eBGP` | BGP のみの論理障害 |

### 2. Observation

SYSLOG を Incident ではなく観測事実として正規化します。

```python
Observation:
    observed_at: datetime
    received_at: datetime | None
    source_node: str
    observed_object: str
    assertion: str          # fault / recovery / state_change / noise
    signature: str | None
    severity: int
    raw_message: str
    confidence: float
    peer_device: str | None
```

例:

```text
%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down
  -> Interface:Leaf1:GigabitEthernet0/0

%BGP-5-ADJCHANGE: neighbor 10.1.11.1 Down
  -> BGPSession:Spine1-Leaf1-eBGP
```

### 3. Hypothesis Scoring

Observation 群を説明できる root cause object を候補化し、score を計算します。

| Score component | 意味 |
|---|---|
| `coverage` | 候補が説明できる Observation 数 |
| `specificity` | Device より Link / Interface / Session を優先する条件 |
| `direct_evidence` | 候補自身が直接観測された強さ |
| `evidence_strength` | Observation confidence の平均 |
| `silent_peer` | 複数装置が同じ peer down を報告した場合の silent root 根拠 |
| `temporal_fit` | 原因らしい観測が影響観測より先にあるか |
| `contradiction` | recovery など候補を否定する根拠 |
| `redundancy` | 冗長経路が残る場合の broad device hypothesis 減点 |
| `link_coherence` | 複数観測を同一 PhysicalLink が説明できる場合の加点 |
| `topology_distance` | 原因候補から観測対象までの距離 |

score component は `rca_explanation` に保存され、API/UI/AI レポートから確認できます。

### 4. Observation Buffer

受信順だけで確定せず、短い event time window で再評価します。Leaf 側の BGP down が先に届き、あとから Spine/Link の証拠が届いた場合でも、`RCA_REVISED` として root cause を改訂できます。

### 5. Incident Projection

`RCAResult` は `IncidentProjector` により既存の `Incident` モデルへ変換されます。

| Incident field | 生成元 |
|---|---|
| `root_cause_node` | `root_cause_object` の代表 Device |
| `primary_event` | 最初の Observation raw message |
| `secondary_nodes` | root 以外の発報元 node |
| `raw_logs` | Observation の raw message |
| `rca_explanation` | Hypothesis score component |

---

## 動作例

### 物理リンク障害

```text
Leaf1 : %LINK-3-UPDOWN Interface Gi0/0 down
Spine1: %LINK-3-UPDOWN Interface Gi0/0 down
Leaf1 : %BGP-5-ADJCHANGE neighbor Spine1 down
```

結果:

```text
root_cause_object = PhysicalLink:Leaf1:Gi0/0--Spine1:Gi0/0
root_cause_node   = Spine1 または Leaf1 の代表Device
secondary_nodes   = 発報元のうち代表root以外
```

### Spine 障害

```text
Leaf1: %BGP-5-ADJCHANGE neighbor Spine1 down
Leaf2: %BGP-5-ADJCHANGE neighbor Spine1 down
Leaf3: %BGP-5-ADJCHANGE neighbor Spine1 down
```

結果:

```text
root_cause_object = Device:Spine1
secondary_nodes   = [Leaf1, Leaf2, Leaf3]
```

### BGP セッション障害

```text
Leaf1: %BGP-5-ADJCHANGE neighbor Spine1 down
```

結果:

```text
root_cause_object = BGPSession:Spine1-Leaf1-eBGP
```

### Silent peer 障害

```text
Spine1: %BGP-5-ADJCHANGE neighbor Leaf2 down
Spine2: %BGP-5-ADJCHANGE neighbor Leaf2 down
```

結果:

```text
root_cause_object = Device:Leaf2
secondary_nodes   = [Spine1, Spine2]
```

---

## 復旧 Lifecycle

Incident は `status` と `condition` を分けて管理します。

| field | 値 | 意味 |
|---|---|---|
| `status` | `OPEN` | 対応中、未クローズ |
| `status` | `CLOSED` | オペレーターが手動クローズ済み |
| `condition` | `ACTIVE` | 障害継続中 |
| `condition` | `DEGRADED` | 一部だけ復旧 |
| `condition` | `RECOVERING` | root cause または関連 object の復旧を検知し、quiet period 中 |
| `condition` | `RECOVERED` | quiet period 中に再障害なし |
| `condition` | `FLAPPING` | 復旧後に再障害を検知 |

復旧 SYSLOG は新規 Incident を作らず、既存 OPEN Incident に対応付けます。quiet period は `RECOVERY_QUIET_PERIOD_SEC`、flapping 判定は `RECOVERY_FLAP_THRESHOLD` で調整します。

---

## トポロジー定義

標準の検証トポロジーは [configs/clos/yang_topology.yaml](configs/clos/yang_topology.yaml) です。

```yaml
network-model:
  physical-layer:
    device:
      - device-id: "Spine1"
        role: spine
        loopback: "10.0.0.1/32"
        node-monitor-enabled: true
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

  layer3-layer:
    bgp-session:
      - session-id: "Spine1-Leaf1-eBGP"
        type: ebgp
        endpoint:
          - device-id: "Spine1"
          - device-id: "Leaf1"
```

重要な前提:

- `device-id` は SYSLOG の hostname と一致させます。
- `physical-connection.endpoint` には `device-id` と `interface-id` が必要です。
- interface IP と loopback は BGP peer IP から device を逆引きするために使います。
- `GigabitEthernet0/0` と `GE0/0` のような一般的な Cisco 略称は正規化されます。

---

## SYSLOG Knowledge Base

SKB は SYSLOG を運用上の意味へ分類します。設定例は [configs/syslog_knowledge/rules.yaml](configs/syslog_knowledge/rules.yaml) です。

| classification / action | 取り扱い |
|---|---|
| `fault-signal` / `create_incident` | 新規 Incident 候補 |
| `state-change` / `correlate_only` | 単独または周辺 Observation と相関して Incident 候補 |
| `recovery` | 既存 Incident の lifecycle 更新 |
| `retain-only` / `noise` | Raw log として保持し、RCA には使わない |
| `unknown` | 低 confidence の Device Observation として扱う |

詳細は [configs/syslog_knowledge/README.md](configs/syslog_knowledge/README.md) を参照してください。

---

## API

| メソッド | パス | 説明 |
|---|---|---|
| `POST` | `/ingest` | SYSLOG を投入し、hypothesis 経路で Incident を生成・更新 |
| `GET` | `/debug/status` | topology / RCA engine / 受信数 / Incident 数を確認 |
| `POST` | `/debug/rca/hypothesis` | 保存・通知なしで legacy と hypothesis の RCA 結果を比較 |
| `POST` | `/debug/rca/migration-readiness` | ラベル付きサンプルで hypothesis の実用性を評価 |
| `GET` | `/incidents` | Incident 一覧 |
| `GET` | `/incidents/{id}` | Incident 詳細 |
| `PUT` | `/incidents/{id}/resolve` | Incident を `CLOSED` にする |
| `GET` | `/incidents/{id}/rca-history` | RCA 再評価履歴 |
| `GET` | `/topology/graph` | UI 用トポロジーグラフ |
| `POST` | `/topology/reload` | トポロジー再読み込み |
| `GET` | `/raw-logs` | Raw SYSLOG 検索 |
| `GET` | `/knowledge/rules` | SKB ルール一覧 |
| `GET` | `/knowledge/unknown-events` | 未知 SYSLOG 一覧 |
| `WS` | `/ws/incidents` | Incident / lifecycle / investigation のリアルタイム通知 |

### `/ingest` 例

```bash
curl -s http://localhost:8080/ingest \
  -H 'content-type: application/json' \
  -d '{
    "messages": [
      {
        "source_ip": "127.0.0.1",
        "raw": "<35>Sep 5 08:13:06 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"
      }
    ]
  }'
```

### RCA 比較

```bash
curl -s http://localhost:8080/debug/rca/hypothesis \
  -H 'content-type: application/json' \
  -d '{"messages":[{"raw":"<35>Sep 5 08:13:06 Leaf2 %BGP-5-ADJCHANGE: neighbor Spine1 down"}]}'
```

### 移行・実用性評価

```bash
curl -s http://localhost:8080/debug/rca/migration-readiness \
  -H 'content-type: application/json' \
  -d '{
    "min_accuracy": 0.8,
    "min_confidence": 0.6,
    "samples": [
      {
        "sample_id": "clos-link-spine1-leaf2",
        "expected_root_cause_object": "PhysicalLink:Leaf2:GigabitEthernet0/0--Spine1:GigabitEthernet0/1",
        "messages": [
          {"raw": "<35>Sep 5 08:13:06 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"},
          {"raw": "<35>Sep 5 08:13:06 Spine1 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down"}
        ]
      }
    ]
  }'
```

---

## 設定

| 変数 | デフォルト | 説明 |
|---|---|---|
| `RCA_ENGINE` | `hypothesis` | `hypothesis` / `dual` / `legacy` |
| `TOPOLOGY_PATH` | `configs/clos/yang_topology.yaml` in Makefile | トポロジー YAML |
| `TOPOLOGY_SOURCE` | `iida-yaml` | トポロジー形式 |
| `SKB_PATH` | なし | SKB YAML ファイルまたはディレクトリ |
| `SYSLOG_IGNORE_FILE` | なし | 追加の無視パターン |
| `API_HOST` | `0.0.0.0` | API bind address |
| `API_PORT` | `8080` | API port |
| `SYSLOG_HOST` | `0.0.0.0` | SYSLOG UDP bind address |
| `SYSLOG_PORT` | `1514` | SYSLOG UDP port |
| `RECOVERY_QUIET_PERIOD_SEC` | `30.0` | recovery 後に `RECOVERED` へ進むまでの静穏期間 |
| `RECOVERY_FLAP_THRESHOLD` | `2` | flapping とみなす再障害回数 |
| `DATABASE_URL` | `sqlite:///./incidents.db` | Incident DB |
| `VIGIL_URL` | なし | vigil 連携 URL |
| `AI_ENABLED` | `false` | AI レポート有効化 |
| `LLM_PROVIDER` | `openai` | `openai` / `ollama` |
| `INVESTIGATION_ENABLED` | `false` | pyATS 調査エージェント有効化 |
| `PYATS_TESTBED_FILE` | なし | pyATS testbed YAML |
| `MAINTENANCE_DIR` | なし | メンテナンス計画 YAML ディレクトリ |
| `AUTH_ENABLED` | `false` | Bearer token 認証 |
| `AUTH_READER_TOKEN` | なし | reader token |
| `AUTH_OPERATOR_TOKEN` | なし | operator token |
| `AUTH_ADMIN_TOKEN` | なし | admin token |
| `CORS_ORIGINS` | `*` | 許可 origin。認証有効時は明示指定が必要 |

---

## メンテナンス計画

`MAINTENANCE_DIR` に YAML を置くと、計画時間中の対象機器・対象ログによる Incident を自動的に `CLOSED` にできます。

```yaml
maintenance-plans:
  plan:
    - plan-id: "CHG-2026-0001"
      title: "Spine1 maintenance"
      scheduled-start: "2026-09-05T01:00:00+09:00"
      scheduled-end: "2026-09-05T03:00:00+09:00"
      status: planned
      affected-device:
        - device-id: "Spine1"
          scope: including-links
      expected-syslog-pattern:
        - "%LINK-3-UPDOWN"
        - "%BGP-5-ADJCHANGE"
```

---

## AI レポートと装置調査

`AI_ENABLED=true` で Incident 詳細から AI 障害レポートを生成できます。RCA の confidence、score component、代替候補がプロンプトに渡されます。

`INVESTIGATION_ENABLED=true` と `PYATS_TESTBED_FILE` を設定すると、pyATS で実機へ read-only 接続し、LLM が調査コマンドを選択します。実行可能なコマンドは `show` / `display` 系に制限されています。

---

## テスト

```bash
make test
```

新方式の主要回帰だけ確認する場合:

```bash
pytest -q \
  src/tests/test_hypothesis_api.py \
  src/tests/test_api_ingest.py \
  src/tests/test_hypothesis_scoring.py \
  src/tests/test_incident_projector.py \
  src/tests/test_observation.py \
  src/tests/test_causal_topology.py \
  src/tests/test_hypothesis_rca_poc.py
```

---

## 実用性の見方

1. `make restart` で hypothesis 経路を起動します。
2. リンク停止、装置停止、BGP session down、復旧ログを投入します。
3. UI または `/incidents` で root cause と secondary nodes を確認します。
4. `/debug/rca/hypothesis` で score component を確認します。
5. ラベル付きサンプルを `/debug/rca/migration-readiness` に投入し、`ready`、`hypothesis_accuracy`、`average_hypothesis_confidence` を見ます。

切り戻し:

```bash
RCA_ENGINE=legacy make restart
```

---

## 関連ドキュメント

| ファイル | 内容 |
|---|---|
| [README.hypothesis-rca.md](README.hypothesis-rca.md) | 新方式の実装計画と進捗 |
| [README.concept.md](README.concept.md) | 初期コンセプト |
| [README.implementation.md](README.implementation.md) | 旧実装計画の履歴 |
| [configs/syslog_knowledge/README.md](configs/syslog_knowledge/README.md) | SKB ルール運用 |
| [yang/README.md](yang/README.md) | YANG モデル概要 |
