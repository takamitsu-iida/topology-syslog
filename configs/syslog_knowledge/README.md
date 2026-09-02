# SYSLOG Knowledge Base (SKB) ルール記法

このディレクトリの YAML ファイルは、SYSLOG の分類、Severity ごとの処理方針、調査手順を定義する SKB の正本です。

有効化するには、アプリケーションに次を設定します。

```bash
SKB_PATH=configs/syslog_knowledge
```

`SKB_PATH` には単一の `.yaml` / `.yml` ファイル、または YAML ファイルを含むディレクトリを指定できます。ディレクトリ指定時は直下の全 YAML ファイルを読み込みます。ファイルを直接編集した場合は、次の SYSLOG 照合時に変更を検知して再読み込みします。

## 最小構成

```yaml
rules:
  - id: cisco-bgp-adjchange
    signature: "%BGP-*-ADJCHANGE"
    status: approved
```

YAML の最上位は `rules:` を持つ形式、またはルールの配列を直接書く形式のどちらも使用できます。

## ルール項目

| 項目 | 必須 | 説明 |
|---|---:|---|
| `id` | 必須 | SKB 内で一意のルール ID。英小文字、数字、`-` を推奨します。 |
| `signature` | 必須 | 正規化済み SYSLOG シグネチャの照合パターン。`*` をワイルドカードとして使えます。 |
| `description` | 任意 | このルールの目的、想定事象、運用上の扱いを説明する文章です。YAML、API、レビュー画面で参照できます。 |
| `vendor` | 任意 | ベンダー識別子。Cisco IOS は `cisco-ios`。指定しない場合は全ベンダーに一致します。 |
| `classification` | 任意 | 人間が読むための事象分類です。 |
| `correlation_role` | 任意 | 相関上の意味を記すメタデータです。推奨値は `root-cause-candidate`、`secondary-impact`、`informational`。 |
| `severity_policy` | 任意 | Severity の範囲ごとのアクション。未指定時は既存の推論設定を維持します。 |
| `dedup_window_sec` | 任意 | 将来の重複抑止用の秒数。現在の推論処理では未使用です。 |
| `runbook` | 任意 | 調査コマンドまたは手順の文字列配列。照合結果とレビュー画面に付与されます。 |
| `status` | 任意 | `approved`、`pending`、`disabled`。省略時は `pending`。 |
| `confidence` | 任意 | ルールの信頼度。通常は `0.0` から `1.0` の数値を設定します。 |
| `priority` | 任意 | 競合時の優先度。大きい値を優先し、省略時は `0`。 |

## シグネチャ

Cisco 形式の `%FACILITY-SEVERITY-MNEMONIC` は、パーサーが Severity を `*` に正規化します。

| 受信 SYSLOG | 正規化シグネチャ |
|---|---|
| `%BGP-3-ADJCHANGE: neighbor down` | `%BGP-*-ADJCHANGE` |
| `%BGP-5-ADJCHANGE: neighbor down` | `%BGP-*-ADJCHANGE` |
| `%LINK-2-INTVULN: ...` | `%LINK-*-INTVULN` |

`signature` の照合には Python の `fnmatch` を使います。`*` は任意長の文字列に一致します。Cisco ルールは、通常 `vendor: cisco-ios` と `%FACILITY-*-MNEMONIC` を組み合わせて記述してください。

Cisco 形式でないメッセージは、IP アドレスを `<ip>`、数値を `<n>` に置換し、大文字化・空白正規化した文字列で照合します。

```yaml
- id: generic-link-alarm
  signature: "LINK DOWN ON <ip>:<n>"
  status: pending
```

複数の承認済みルールが一致した場合は、`priority` が最大のルールを採用します。同じ `priority` なら、より長い `signature` を優先します。同値の場合は YAML 内で先に読み込まれたルールが残ります。

## Severity ポリシー

SYSLOG Severity は `0=EMERGENCY` から `7=DEBUG` です。キーは単一値の文字列、または範囲の文字列で指定します。

```yaml
severity_policy:
  "0-2": page_immediately
  "3": create_incident
  "4-5": correlate_only
  "6-7": retain_only
```

使用できるアクションは次の 4 種類です。

| アクション | 即時受信処理での動作 |
|---|---|
| `page_immediately` | 通常どおりインシデントを作成し、既存の通知経路を使用します。 |
| `create_incident` | 通常どおりインシデントを作成します。 |
| `correlate_only` | 新規インシデントと通知は作成せず、関連する既存 OPEN インシデントがあればログを統合します。 |
| `retain_only` | インシデント推論・通知を行いません。SKB 適用履歴には残ります。 |

範囲は `0` から `7` の昇順で記述します。重複した範囲を避け、全 Severity を明示的に扱う場合は `"0-7"` を使います。

## 状態と編集手順

新規ルールは、まず `pending` として登録します。`pending` と `disabled` のルールは照合に使われません。内容を確認してから `approved` に変更してください。

```yaml
- id: cisco-cdp-native-vlan-mismatch
  vendor: cisco-ios
  signature: "%CDP-*-NATIVE_VLAN_MISMATCH"
  classification: native-vlan-mismatch
  correlation_role: secondary-impact
  severity_policy:
    "0-3": create_incident
    "4-5": correlate_only
    "6-7": retain_only
  runbook:
    - "show interfaces trunk"
    - "show cdp neighbors detail"
  status: pending
  confidence: 0.6
  priority: 80
```

レビュー UI の `/knowledge`、または API でも編集できます。

| 操作 | API |
|---|---|
| 一覧 | `GET /knowledge/rules` |
| 保留ルール作成 | `POST /knowledge/rules` |
| 編集 | `PUT /knowledge/rules/{rule_id}` |
| 承認 | `POST /knowledge/rules/{rule_id}/approve` |
| 無効化 | `POST /knowledge/rules/{rule_id}/disable` |
| 版指定ロールバック | `POST /knowledge/rules/{rule_id}/rollback/{version}` |
| 監査履歴 | `GET /knowledge/audit` |

API 操作の実行者は `X-Actor` ヘッダーに記録できます。

```bash
curl -X POST http://localhost:8080/knowledge/rules/cisco-cdp-native-vlan-mismatch/approve \
  -H 'X-Actor: network-operator@example.com'
```

## 運用上の注意

- `approved` は即時に自動判定へ影響するため、未知イベントから作成したルールは必ず `pending` でレビューします。
- `retain_only` は生 SYSLOG の外部ログ転送を削除しません。ここで抑制するのは本サービスのインシデント推論・通知です。
- `correlation_role` はルールに記録・API 表示されますが、現時点の根本原因推論アルゴリズムの重み付けには使用していません。
- Docker Compose の `configs` は読み取り専用でマウントされます。コンテナ内のレビュー API でルールを保存する運用では、書き込み可能な `SKB_PATH` を別ボリュームに指定してください。Git 管理のサンプルを直接編集する運用では、ホスト側で編集してコンテナを再起動またはリロード対象のファイルを更新します。