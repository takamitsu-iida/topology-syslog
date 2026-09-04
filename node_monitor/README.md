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

## API 契約

初期バージョンは監視サービスが次の read-only API を公開します。

```text
GET /v1/nodes/{node_id}/state
GET /v1/nodes/states?node_id=Spine1&node_id=Spine2
GET /healthz
```

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

## 最初の着手範囲

最初は Step 1 のみを実装します。実ネットワークへのプローブ、Docker Compose、RCA の挙動変更はまだ加えません。状態モデルとストアをテストで固めてから、外部 I/O を持つ Step 2 へ進みます。