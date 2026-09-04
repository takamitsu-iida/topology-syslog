# Node State Monitor

ネットワーク装置の到達性と稼働状態を継続観測し、他コンポーネントが参照できる状態スナップショットを提供するサービスの設計・実装計画です。

## 目的

SYSLOG 相関エンジンは状態確認を実行せず、トポロジーと SYSLOG から根本原因候補を作ります。本サービスは独立してノード状態を観測し、RCA はその結果を証拠として利用します。

この分離により、Spine 停止時に複数 Leaf から BGP `neighbor ... Down` が同時到着しても、同じ Spine への確認を一度に集約できます。また、SSH/NETCONF 認証情報を API サービスから隔離できます。

## 配置と実行方式

当面はこのリポジトリ内の独立パッケージ・独立コンテナとして実装します。

```text
node_monitor/
  README.md
  topology_syslog_node_monitor/
    models.py
    store.py
    probes.py
    scheduler.py
    service.py
    api.py
  tests/
  Dockerfile
```

Docker Compose では `backend` と別の `node-monitor` サービスとして実行します。`node-monitor` のみが装置管理ネットワークと SSH/NETCONF 認証情報へアクセスします。`backend` は HTTP API を通じて状態を読むだけとします。

将来、監視専用ホストや別ネットワークへ移す場合は、同じコンテナイメージを移設します。API 契約を維持できれば、別リポジトリ化は不要です。複数システムで共有する、独立したリリース・可用性要件が生じる段階で別リポジトリ化を検討します。

## 状態モデル

ノードごとに次の状態を管理します。

| 状態 | 意味 |
|---|---|
| `UP` | 少なくとも一つの有効なプローブが成功した |
| `DOWN` | 複数の独立した確認が失敗し、停止と判断できる |
| `DEGRADED` | 管理到達性はあるが BGP、SSH、NETCONF など必要な確認の一部が失敗した |
| `UNKNOWN` | 未確認、結果期限切れ、または ICMP 遮断などで判断不能 |

各状態レコードには、`node_id`、`state`、`observed_at`、`expires_at`、`probes`、`reason`、`monitor_id` を含めます。`probes` には試行した方式、成功可否、遅延、エラー概要を保存します。

## 実装済み動作の流れ

Spine が停止した場合、node-monitor は定期確認で ICMP と TCP/179 の結果を集約します。異なるプローブが失敗して `DOWN` になると、状態変化イベントを一度だけ生成し、webhook の bounded queue から backend へ非同期送信します。

backend はイベントを受信すると、次の処理を行います。

1. 共有トークンを検証し、`event_id` を永続ストアへ登録する。
2. 同じ `event_id` の重複イベントは再処理しない。
3. `root_cause_node`、`secondary_nodes`、トポロジーの順に関連する OPEN インシデントを検索する。
4. 関連インシデントへ `node-monitor` evidence を追加し、RCA confidence と履歴を更新する。
5. 必要に応じて WebSocket の `incident.updated` を UI へ送信する。

状態復旧時は、`UP` イベントだけで即時クローズしません。関連インシデントを `DEGRADED -> RECOVERING` とし、quiet period 経過後に `RECOVERED` へ遷移します。quiet period 中に新しい障害イベントが到着した場合は、復旧タスクを無効化して復旧確定を行いません。

イベントはノードごとの `observed_at` で順序管理します。遅れて到着した古いイベントは `STALE` として受け付けますが、現在のインシデント状態を古い状態へ戻しません。`UNKNOWN` は装置停止とは断定せず、監視不能・期限切れ・プローブ不能として記録します。

node-monitor と backend のどちらかが停止しても、node-monitor のプローブ処理は継続します。webhook 配送は timeout と指数バックオフで再試行し、終了時に未配送キューを破棄してプロセス停止を妨げません。
`ping` の失敗のみで `DOWN` にしません。ICMP フィルタ、管理経路断、CoPP と装置停止を区別できないためです。ICMP、TCP/179、SSH/NETCONF の組み合わせと、連続失敗回数で状態を決めます。

## 監視対象の選択

監視対象はトポロジー YAML の各 `physical-layer.device` にある `node-monitor-enabled` で指定します。未指定時は `false` であり、トポロジーには存在しても node-monitor はプローブしません。

```yaml
- device-id: "Spine2"
  role: spine
  loopback: "10.0.0.2/32"
  node-monitor-enabled: true
```

プローブ先は有効化されたノードの `loopback` を優先し、未設定時だけインターフェース IP を使います。

`node-monitor` は `NODE_MONITOR_TOPOLOGY_PATH` で指定されたトポロジーを読み込み、`node-monitor-enabled: true` のノードだけを起動時に登録します。現在の CLOS 構成では `Spine1`、`Spine2`、`Leaf1`、`Leaf2`、`Leaf3` が対象です。

## 実行間隔と状態確認

デフォルトでは起動直後に全対象ノードを一度確認し、その後 **30 秒間隔** で定期確認します。

```text
NODE_MONITOR_INTERVAL_SEC=30       # 定期確認の間隔
NODE_MONITOR_TTL_SEC=60             # 正常状態を再利用できる期間
NODE_MONITOR_MIN_CHECK_INTERVAL_SEC=5
NODE_MONITOR_MAX_FAILURE_BACKOFF_SEC=300
NODE_MONITOR_PROBE_TIMEOUT_SEC=2
NODE_MONITOR_MAX_CONCURRENT_CHECKS=10
```

各定期確認では、対象ノードに対して ICMP と設定された TCP ポートを確認します。現在の TCP ポートの既定値は `179` です。`TcpProbe` は TCP 接続を開いて閉じるだけで、SSH ログインや認証、コマンド実行は行いません。

状態判定は次のとおりです。

- 成功したプローブが一つ以上あれば `UP`。
- 成功プローブがあり、必須プローブが失敗した場合は `DEGRADED`。
- 異なるプローブ方式が二つ以上失敗した場合は `DOWN`。
- 一つの失敗だけ、未観測、期限切れ、プローブ実行不能は `UNKNOWN`。

正常状態は TTL 内では再プローブせず、結果を再利用します。失敗時はノード単位で最短確認間隔を適用し、指数バックオフします。同一ノードへの同時確認は single-flight で一つに集約され、全ノードを合わせた同時確認数も制限されます。

## 起動と停止

Docker Compose では `backend`、`frontend`、`node-monitor` を別サービスとして起動します。開発環境では Makefile から同じ構成を起動できます。

```bash
make start          # node-monitor、backend、frontend を起動
make stop           # frontend、backend、node-monitor を停止
make status         # 3 プロセスの状態を表示
make logs-monitor   # node-monitor のログを表示
```

node-monitor は既定で `http://localhost:8090`、backend は `NODE_MONITOR_URL` を通じて `http://127.0.0.1:8090` を参照します。各プロセスの PID は `.pids/`、ログは `logs/` に保存されます。

## API 契約

初期バージョンは監視サービスが次の read-only API を公開します。

```text
GET /v1/nodes/{node_id}/state
GET /v1/nodes/states?node_id=Spine1&node_id=Spine2
GET /healthz
GET /metrics
```

状態 API は read-only です。`NODE_MONITOR_API_TOKEN` が設定されている場合、`/v1/nodes/*` と `/metrics` には `Authorization: Bearer <token>` が必要です。`/healthz` も同じ認証ミドルウェアの対象です。

個別状態のレスポンス例です。

```json
{
  "node_id": "Spine2",
  "state": "DOWN",
  "observed_at": "2026-09-04T10:00:05Z",
  "expires_at": "2026-09-04T10:01:05Z",
  "reason": "icmp and tcp/179 probes failed",
  "probes": [
    {"type": "icmp", "target": "10.0.0.2", "success": false},
    {"type": "tcp", "target": "10.0.0.2:179", "success": false}
  ]
}
```

イベント契機の即時確認は、初期の REST API に追加せず、モニター内部の状態遷移ルールで吸収します。必要になった段階で、認証済みの `POST /v1/checks` を追加し、`node_id` 単位で要求を集約します。

## 重複排除と負荷制御

- 同一 `node_id` の確認は single-flight とし、実行中の確認結果を待機要求で共有する。
- ノードごとに最短実行間隔を設け、直近結果が TTL 内なら再実行しない。
- 全体の同時プローブ数を制限し、タイムアウトと指数バックオフを設定する。
- 定期監視とイベント起因確認には優先度を設け、後者を優先する。
- `DOWN` 後も低頻度で再確認し、復旧を検出する。

## 運用観測

`/metrics` は Prometheus 互換のテキスト形式で、完了した確認数と状態遷移数を公開します。

```text
node_monitor_checks_total{state="UP"} 12
node_monitor_state_changes_total{state="DOWN"} 1
```

状態が変化したときは `node_state_changed` イベントを JSON 形式でログ出力します。ログにはノード ID、変更前後の状態、判定理由が含まれます。`UNKNOWN` は装置停止を意味せず、未確認・期限切れ・プローブ不能、または node-monitor 自体の通信障害を表します。

## RCA との統合

`RootCauseInferencer` は `NodeStateReader` プロトコルだけに依存します。モニターが停止・未接続の場合は `UNKNOWN` として、現在の SYSLOG とトポロジーによる推論を継続します。

| peer 状態 | RCA の扱い |
|---|---|
| `DOWN` | 無発報 peer を強い根本原因候補にし、観測結果を `RCAEvidence` に追加する |
| `UP` | peer 自体の停止候補を下げ、BGP セッション、経路、ACL、制御プレーンを代替候補として示す |
| `DEGRADED` | 停止断定は避け、劣化状態を根拠として候補を提示する |
| `UNKNOWN` | 状態証拠を加えず、既存のサイレント推論を使う |

RCA の同期パスからネットワーク I/O を排除します。状態が古い場合は、`observed_at` と鮮度を evidence に記録し、確信度を上げません。

## 実装ステップ

### Step 1: ドメインモデルとインメモリストア

- `NodeState`、`ProbeResult`、`NodeStateReader` を定義する。
- `InMemoryNodeStateStore` に TTL と期限切れ時の `UNKNOWN` を実装する。
- 状態遷移と期限切れの単体テストを追加する。

完了条件: プローブを実行せず、固定データで単一・複数ノードの状態を取得できる。

### Step 2: プローブ抽象化と安全な ICMP/TCP 実装

- `Probe` プロトコルを定義し、実装を `IcmpProbe` と `TcpProbe` に分ける。
- シェル文字列を組み立てず、引数配列と厳格なタイムアウトを使う。
- IP アドレスはトポロジー定義からだけ取得し、任意入力を接続先にしない。
- 成功、失敗、タイムアウト、実行不可を区別するテストを追加する。

完了条件: テストダブルを使い、複数プローブ結果から `UP`、`DEGRADED`、`DOWN`、`UNKNOWN` を決定できる。

### Step 3: スケジューラーと確認集約

- 定期監視スケジューラーを実装する。
- `node_id` 単位の single-flight、TTL キャッシュ、ノード別レート制限、全体同時実行上限を追加する。
- プローブ失敗時のバックオフと `DOWN` ノードの復旧確認を実装する。

完了条件: 同じ Spine に対する同時確認要求が多数あっても、実プローブが一回だけ起動される。

### Step 4: HTTP API とコンテナ分離

- FastAPI の read-only API と `/healthz` を実装する。
- `node-monitor` 用 Dockerfile、Compose サービス、専用の環境変数を追加する。
- 監視サービスだけに認証情報と管理ネットワーク経路を与える。

完了条件: `backend` と別プロセスで動作し、HTTP 経由で期限付き状態を取得できる。

### Step 5: トポロジーと装置情報の統合

- `configs/clos/yang_topology.yaml` の loopback とインターフェース IP をプローブ対象として解決する。
- 既存の `configs/clos/testbed.yaml` を参照し、必要なら SSH/NETCONF プローブを追加する。
- 接続先や資格情報の不足を `UNKNOWN` として記録する。

完了条件: CLOS の `Spine2` を ID 指定すると、管理 IP と必要な確認方式が決定される。

### Step 6: RCA への読み取り専用統合

- `backend` に `NodeStateReader` の HTTP クライアントを追加する。
- BGP peer Down のサイレント候補に状態 evidence を付与し、確信度ルールを追加する。
- モニターのタイムアウト・障害時は `UNKNOWN` として既存推論へフォールバックする。

完了条件: `Spine2=DOWN`、`UP`、`UNKNOWN` の各ケースで RCA の候補・確信度・根拠がテストで説明可能になる。

### Step 7: 運用機能

- 状態変化、プローブ失敗率、確認待ち時間のメトリクスと構造化ログを追加する。
- API 認証、TLS、監視対象許可リスト、資格情報ローテーションを整備する。
- UI に状態、最終観測時刻、観測根拠を表示する。

完了条件: 監視サービス自身の異常と、装置の `UNKNOWN` を運用者が区別できる。

## 追加実装計画: 状態変化のインシデント反映

現在の Step 7 までの実装では、node-monitor の状態は定期観測され、backend が SYSLOG 受信時または RCA 実行時に参照します。node-monitor が先にノードの `DOWN` を検知した場合、既存の OPEN インシデントへ自動反映するイベント連携はまだありません。

この機能は、node-monitor から backend へ状態変化だけを通知し、backend が関連するインシデントを更新する方式で追加します。RCA の同期処理からネットワーク I/O を発生させず、同じ状態変化の重複通知にも耐える設計にします。

### Step 8: 状態変化イベント契約

`UP`、`DOWN`、`DEGRADED`、`UNKNOWN` への変化時に、次のイベントを生成します。定期確認で状態が変わらない場合は通知しません。

```json
{
  "event_id": "node-state-Spine2-20260904T100005Z-DOWN",
  "event_type": "node_state.changed",
  "node_id": "Spine2",
  "previous_state": "UP",
  "state": "DOWN",
  "observed_at": "2026-09-04T10:00:05Z",
  "reason": "Independent probes failed.",
  "probes": []
}
```

- `event_id` はノード、観測時刻、遷移後状態から決定的に生成し、重複処理に使う。
- `UNKNOWN` への変化も通知するが、装置停止とは扱わない。
- プローブの詳細は event payload に含め、backend が RCA evidence を再現できるようにする。

完了条件: 状態変化ごとに一意なイベントが生成され、状態不変の定期確認ではイベントが増えない。

実装済み: `NodeStateChangeEvent` を scheduler の状態遷移点で生成し、`event_id`、前後状態、観測時刻、理由、全プローブ結果を保持します。`NodeMonitor.drain_events()` で未配送イベントを取得でき、`on_state_change` コールバックで後続の配送 adapter に接続できます。状態が変化しない確認ではイベントを生成しません。

### Step 9: backend へのイベント配送

まずは node-monitor から backend への HTTP webhook を実装します。将来、複数 backend や高い配送耐久性が必要になった場合はメッセージキューへ置き換えられるよう、配送処理を adapter として分離します。

- `NODE_MONITOR_EVENT_URL` と共有トークンを node-monitor 側だけに設定する。
- backend に認証済み `POST /internal/node-state-events` を追加する。
- 接続タイムアウト、再試行回数、指数バックオフ、送信キュー上限を設定する。
- backend 停止中も観測処理を止めず、未送信イベントを保持できる仕組みを追加する。
- backend は `event_id` を保存またはキャッシュし、同じイベントを二度適用しない。

完了条件: backend が停止・再起動してもイベント配送が観測処理をブロックせず、再送された同一イベントが冪等に処理される。

実装済み: `WebhookEventPublisher` が bounded queue と非同期 worker を使って `POST /internal/node-state-events` へ配送します。HTTP timeout/エラー時は指数バックオフで再試行し、キューが満杯の場合は観測処理をブロックせずイベントを破棄してメトリクス用カウンターを増やします。backend は `NODE_MONITOR_EVENT_TOKEN` を検証し、SQLite/PostgreSQL の `node_state_events.event_id` 主キーで重複イベントを冪等に受け付けます。イベント配送の共有トークンは通常のユーザー認証トークンとは分離しています。

### Step 10: 関連インシデントの特定

backend は状態変化を受信しただけで新規インシデントを作らず、次の順序で既存 OPEN インシデントを検索します。

1. `root_cause_node == node_id` のインシデント
2. `secondary_nodes` に `node_id` を含むインシデント
3. トポロジー上の祖先・子孫と BGP peer Down の関連が確認できるインシデント

該当するインシデントがない場合は、状態を node-monitor のスナップショットとして保持し、SYSLOG が後から到着したときに通常の RCA が参照できるようにします。状態変化だけで新規インシデントを作成するかどうかは、別の運用設定で明示します。

完了条件: 同一ノードに複数の関連インシデントがある場合の選択規則が決まり、無関係なインシデントが更新されない。

実装済み: `POST /internal/node-state-events` は、受信した状態イベントを新規登録した後、OPEN かつ未復旧のインシデントを `root_cause_node`、`secondary_nodes`、トポロジー上の祖先・子孫の順で検索します。レスポンスには `related_incident_ids` と `match_type` (`root_cause`、`secondary_node`、`topology`、`none`) を含めます。この段階ではインシデントの内容や状態は変更せず、状態イベントの関連先を確定する責務に限定しています。重複 `event_id` は再処理せず、冪等な accepted response を返します。

### Step 11: RCA evidence とインシデント状態の更新

`DOWN` のイベントを関連インシデントへ反映し、`RCAEvidence(source="node-monitor")` を追加または更新します。

- `DOWN`: 停止確認の根拠、プローブ結果、観測時刻を追加し、RCA confidence を再計算する。
- `DEGRADED`: 停止とは断定せず、劣化根拠だけを追加する。
- `UNKNOWN`: 既存の停止根拠を上書きせず、観測不能として記録する。
- `UP`: 復旧候補として記録するが、単独でインシデントを自動クローズしない。

既存の SYSLOG evidence と node-monitor evidence を分離し、後から「SYSLOG が先だったのか、状態監視が先だったのか」を追跡できるようにします。更新時には `RCAEvaluationRecord` を作成し、WebSocket の `incident.updated` で UI へ通知します。

完了条件: `DOWN`、`DEGRADED`、`UNKNOWN`、`UP` の各イベントが、関連インシデントの evidence、confidence、監査履歴へ正しく反映される。

実装済み: 関連インシデントごとに `node-monitor` evidence を重複なく追加し、`DOWN` は confidence を 0.30、`DEGRADED` は 0.15 加算して再計算します。`DOWN`/`DEGRADED` のとき `ACTIVE` インシデントは `DEGRADED` へ更新します。`UNKNOWN` と `UP` は自動クローズせず、観測根拠と復旧候補として履歴に記録します。更新時は `RCAEvaluationRecord` を保存し、WebSocket の `incident.updated` を送信します。

### Step 12: 復旧と運用テスト

- `DOWN -> UP` では、復旧確認の quiet period と既存の recovery SYSLOG を組み合わせる。
- node-monitor の停止、backend の停止、HTTP timeout、重複イベント、イベント順序逆転をテストする。
- Spine 1 台停止時に複数 Leaf の BGP Down が到着する CLOS シナリオを統合テストする。
- UI で「装置 DOWN」と「node-monitor unavailable / UNKNOWN」を区別して表示する。
- イベント配送遅延、失敗率、再送数、適用済み・重複イベント数をメトリクスへ追加する。

完了条件: Spine 停止を node-monitor が先に検知しても、関連インシデントが一件に集約され、復旧時に誤クローズや重複更新が発生しない。

実装済み: node-monitor の `UP` は `DEGRADED -> RECOVERING` として扱い、quiet period 経過後に `RECOVERED` へ遷移します。`UP` だけで即時クローズはしません。イベントはノード単位の観測時刻で順序管理し、重複イベントは再処理せず、古いイベントは `STALE` として受け付けるだけでインシデントを巻き戻しません。webhook worker の停止時は未配送キューを破棄して shutdown を阻害しないため、backend 停止やモニター停止でもプローブ処理の終了を妨げません。

## 実装状況

Step 1 から Step 12 まで実装済みです。現在の実装は ICMP/TCP による無認証の到達性確認を対象とし、SSH/NETCONF によるログイン確認はまだ実施しません。将来追加する場合も、別プローブとして認証情報、読み取り専用コマンド、接続制限を分離します。