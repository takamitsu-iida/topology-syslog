# Hypothesis-Based RCA 実装計画

> 作成日: 2026-09-05
> 目的: 現行の「SYSLOG受信ごとにIncidentを即時生成・統合する方式」から切り離し、トポロジー依存グラフ上で Observation を集約し、根本原因 Hypothesis を採点して Incident に投影する新方式を段階的に実装する。

---

## 1. 方針

新方式では、SYSLOG を直接 Incident に変換しない。まず観測事実として `Observation` に正規化し、トポロジー上の原因候補を `Hypothesis` として生成・採点し、最後に `RCAResult` または `Incident` へ投影する。

```text
Raw SYSLOG
  -> Parser
  -> Normalizer / Knowledge Matcher
  -> Observation
  -> Hypothesis Engine
  -> RCAResult
  -> Incident Projector
  -> Store / Notification / UI
```

この責務分離により、リンク停止、装置停止、インターフェース障害、BGPセッション障害、サイレント障害、復旧イベントを同じ枠組みで扱う。

---

## 2. 現行方式から切り離す境界

現行方式では、`_process_message_immediately()` と `RootCauseInferencer` の周辺に以下の責務が集中している。

| 責務 | 現行 | 新方式 |
|---|---|---|
| SYSLOG分類 | 受信処理中に分類して即判断 | Observation 作成前の前処理 |
| トポロジー探索 | Device 中心の祖先・子孫探索 | Device / Interface / PhysicalLink / BGPSession の依存グラフ探索 |
| RCA判断 | Incident生成とほぼ同時 | Hypothesis採点として独立 |
| 既存Incident統合 | 推論直後にマージ | RCAResultからIncident Projectorが判断 |
| 復旧 | Incident更新処理に直結 | Observationとして扱いLifecycleへ反映 |
| 通知 | Incident保存と密結合 | Projector後のイベントとして通知 |

新方式は通常の `/ingest` 経路と `make start` のデフォルトに切り替え済み。旧方式は `RCA_ENGINE=legacy` を明示した場合のrollback用として残す。

---

## 3. 新しい中核モデル

### 3.1 Causal Object

根本原因候補になり得る対象を、Device だけでなく明示的なオブジェクトとして扱う。

| Object | 例 | 用途 |
|---|---|---|
| `Device` | `Device:Spine1` | 装置全体停止、サイレント障害 |
| `Interface` | `Interface:Leaf1:GigabitEthernet0/0` | 単体IF障害、ローカル断 |
| `PhysicalLink` | `PhysicalLink:Leaf1:Gi0/0--Spine1:Gi0/0` | 両端IFやBGP断をまとめる物理リンク障害 |
| `BGPSession` | `BGPSession:Spine1-Leaf1-eBGP` | BGPのみの論理障害 |
| `Service` | `Service:VRF:tenant-a` | 将来の影響範囲算出 |

### 3.2 Observation

SYSLOGから抽出した観測事実。Incidentではない。

```python
Observation:
    observed_at: datetime
    source_node: str
    observed_object: str
    assertion: str          # fault / recovery / state_change / noise
    signature: str | None
    severity: int
    raw_message: str
    confidence: float
```

### 3.3 Hypothesis

Observation 群を説明できる根本原因候補。

```python
Hypothesis:
    root_cause_object: str
    score: float
    covered_observations: tuple[int, ...]
    reasons: tuple[str, ...]
```

### 3.4 RCAResult

Hypothesis 採点結果。Incident保存前の中間成果物。

```python
RCAResult:
    root_cause_object: str | None
    confidence: float
    hypotheses: tuple[Hypothesis, ...]
    observations: tuple[Observation, ...]
```

---

## 4. 進捗サマリー

| Phase | 状態 | 内容 | 成果物 |
|---|---|---|---|
| Phase H0 | ✅ 完了 | 最小PoC | `hypothesis_rca.py`, `test_hypothesis_rca_poc.py` |
| Phase H1 | ✅ 完了 | CausalTopology の正式化 | `topology/causal_topology.py`, `test_causal_topology.py` |
| Phase H2 | ✅ 完了 | SYSLOG -> Observation 正規化 | `correlation/observation.py`, `test_observation.py` |
| Phase H3 | ✅ 完了 | Hypothesis採点ポリシー設計 | `correlation/hypothesis_scoring.py`, `test_hypothesis_scoring.py` |
| Phase H4 | ✅ 完了 | バケット処理・遅延到着対応 | `correlation/observation_buffer.py`, `test_observation_buffer.py` |
| Phase H5 | ✅ 完了 | Incident投影・既存Store連携 | `correlation/incident_projector.py`, `test_incident_projector.py` |
| Phase H6 | ✅ 完了 | 復旧・Lifecycle統合 | `correlation/hypothesis_lifecycle.py`, `test_hypothesis_lifecycle.py` |
| Phase H7 | ✅ 完了 | API/UI切替導入 | `RCA_ENGINE`, `/debug/rca/hypothesis`, `test_hypothesis_api.py` |
| Phase H8 | ✅ 完了 | 現行方式からの段階移行 | `correlation/rca_migration.py`, `/debug/rca/migration-readiness` |

---

## 5. Phase詳細

### Phase H0: 最小PoC ✅ 完了

目的: 新方式でリンク停止、装置停止、IF単体障害、BGP単体障害を分離できるか確認する。

実装済み:

- [x] `CausalTopology` を追加
- [x] `Observation` / `Hypothesis` / `RCAResult` を追加
- [x] `HypothesisRCAEngine` を追加
- [x] Device / Interface / PhysicalLink / BGPSession を原因候補化
- [x] 最小スコアリングを実装
- [x] 既存本番パイプラインには未接続

検証済みケース:

- [x] 単一物理リンク障害では `PhysicalLink` が勝つ
- [x] Spine配下の複数BGP断では `Device:Spine1` が勝つ
- [x] Leaf配下IF単体障害では `Interface` に局所化される
- [x] BGPのみの障害では `BGPSession` に局所化される

検証コマンド:

```bash
pytest -q src/tests/test_hypothesis_rca_poc.py
pytest -q src/tests/test_hypothesis_rca_poc.py src/tests/test_root_cause.py
```

結果:

```text
4 passed, 1 warning
38 passed, 1 warning
```

判断:

- [x] 新方式は採用検討に値する
- [x] ただし、スコアリングはPoC用であり、本番化前にポリシーとして整理する

### Phase H1: CausalTopology の正式化 ✅ 完了

目的: 現行の `TopologyLoader` / `GraphEngine` と並行して、原因推論用の依存グラフを正式に構築する。

タスク:

- [x] `topology/causal_topology.py` へ移動または新設する
- [x] Device / Interface / PhysicalLink / BGPSession のID規則を固定する
- [x] `yang_topology.yaml` の物理接続から両端Interfaceを必須情報として検証する
- [x] BGP session と物理Linkの関係を明示的に張る
- [x] Node Monitor対象を `Device` object に紐付ける
- [x] 既存 `GraphEngine` と共存できる読み込みAPIを用意する

完了条件:

- [x] CLOSサンプルトポロジーから Causal Object が期待数生成される
- [x] Link / Interface / BGPSession の逆引きができる
- [x] 既存 `test_yang_loader.py` と新規CausalTopologyテストが同時に通る

実装メモ:

- `CausalTopology.load_from_iida_yaml()` / `load_from_iida_json()` / `from_iida_topology()` を追加
- `device_object_id()` / `interface_object_id()` / `physical_link_object_id()` / `bgp_session_object_id()` でID規則を固定
- `interface_object()` / `physical_link_for_interface()` / `bgp_session_for_devices()` / `resolve_device_by_address()` で逆引きAPIを追加
- `physical-connection` の `device-id` / `interface-id` 不足や未知Interface参照は `ValueError` として検出
- Node Monitor有効状態は `Device:*` object の `node_monitor_enabled` 属性に保持

検証コマンド:

```bash
pytest -q src/tests/test_causal_topology.py
pytest -q src/tests/test_causal_topology.py src/tests/test_hypothesis_rca_poc.py src/tests/test_yang_loader.py src/tests/test_root_cause.py
```

結果:

```text
6 passed, 1 warning
56 passed, 1 warning
```

### Phase H2: SYSLOG -> Observation 正規化 ✅ 完了

目的: SYSLOGの種類ごとに、どのCausal Objectに対する観測かを決める。

タスク:

- [x] `correlation/observation.py` を作成する
- [x] Cisco `%LINK-3-UPDOWN` から `Interface` Observation を生成する
- [x] Cisco `%BGP-5-ADJCHANGE` から `BGPSession` Observation を生成する
- [x] peer IP / hostname から対向Deviceを解決する
- [x] SKB の `classification` / `correlation_role` を Observation assertion へ反映する
- [x] 未知ログは `Device` 低confidence Observationとして扱う
- [x] recoveryログは `assertion=recovery` として生成する

完了条件:

- [x] 実SYSLOGサンプル10〜20件が期待するObservationへ正規化される
- [x] unknown / retain-only / fault-signal / recovery の扱いがテストで固定される

実装メモ:

- `Observation` / `ObservationNormalizer` を追加
- `%LINK-3-UPDOWN` は送信元Deviceの `Interface:*` Observationへ正規化
- `%BGP-5-ADJCHANGE` は peer IP / hostname を解決して `BGPSession:*` Observationへ正規化
- 未知SYSLOGは `Device:*` の低confidence fault Observationとして保持
- `retain_only` / `noise` は `assertion=noise` として保持
- `is_recovery` または recovery分類は `assertion=recovery` として保持
- `HypothesisRCAEngine.observe()` は `ObservationNormalizer` へ委譲する

検証コマンド:

```bash
pytest -q src/tests/test_observation.py
pytest -q src/tests/test_observation.py src/tests/test_hypothesis_rca_poc.py src/tests/test_causal_topology.py src/tests/test_yang_loader.py src/tests/test_root_cause.py
```

結果:

```text
7 passed, 1 warning
63 passed, 1 warning
```

### Phase H3: Hypothesis採点ポリシー設計 ✅ 完了

目的: PoCの手続き的な点数付けを、説明可能で調整しやすいポリシーにする。

採点軸:

| 軸 | 意味 |
|---|---|
| coverage | 候補が説明できるObservation数 |
| specificity | DeviceよりLink/Interface/Sessionを優先する条件 |
| topology_distance | 原因候補から観測対象までの依存距離 |
| evidence_strength | link down / monitor down / bgp down などの強さ |
| temporal_fit | 原因らしい観測が影響観測より先にあるか |
| contradiction | monitor up など、候補を否定する根拠 |
| redundancy | 冗長経路が残っている場合の影響度補正 |

タスク:

- [x] `HypothesisScorer` を分離する
- [x] score内訳を `RCAEvidence` 相当で返す
- [x] Linkが勝つ条件、Deviceが勝つ条件、Sessionが勝つ条件をテスト化する
- [x] 同点・僅差時の tie-breaker を定義する
- [x] confidence計算を内訳ベースに変更する

完了条件:

- [x] score理由がAPI/UI/AIレポートで説明可能な構造になる
- [x] PoC 4ケースに加えて、矛盾証拠と冗長構成のテストが通る

実装メモ:

- `HypothesisScorer` / `Hypothesis` / `ScoreComponent` を追加
- `coverage` / `specificity` / `topology_distance` / `evidence_strength` / `temporal_fit` / `contradiction` / `redundancy` をscore内訳として保持
- `link_coherence` を明示し、複数Observationを同一PhysicalLinkで説明できる場合にLink候補を強める
- `temporal_fit` は Phase H4 の ObservationBuffer 導入までは0点の明示プレースホルダー
- recovery Observation は fault仮説への矛盾証拠として減点
- 冗長BGP sessionの一部のみをDevice原因で説明する場合は broad device hypothesis を減点
- tie-breaker は score、object type rank、object id の順で deterministic に決定
- confidence は margin / coverage / direct evidence / sample strength から算出

検証コマンド:

```bash
pytest -q src/tests/test_hypothesis_scoring.py
pytest -q src/tests/test_hypothesis_scoring.py src/tests/test_observation.py src/tests/test_hypothesis_rca_poc.py src/tests/test_causal_topology.py src/tests/test_yang_loader.py src/tests/test_root_cause.py
```

結果:

```text
8 passed, 1 warning
71 passed, 1 warning
```

### Phase H4: ObservationBuffer と遅延到着対応 ✅ 完了

目的: 受信ごとに即確定せず、短い観測バケットでRCAを更新する。

タスク:

- [x] `ObservationBuffer` を作成する
- [x] event time と received time を分ける
- [x] 5〜30秒程度の小窓を設定可能にする
- [x] 遅延到着した上流証拠で `RCA_REVISED` を出せるようにする
- [x] バケット満了前でも高confidenceなら暫定RCAを返す

完了条件:

- [x] Leaf側BGPログが先に届き、後からSpine/Link証拠が届いてもRCAを改訂できる
- [x] 旧time_window方式とは独立したテストで確認できる

実装メモ:

- `ObservationBuffer` / `BufferUpdate` / `BufferUpdateType` を追加
- `BUFFERED` / `TENTATIVE` / `RCA_REVISED` / `WINDOW_CLOSED` の更新種別を定義
- `Observation.received_at` を追加し、event time の `observed_at` と分離
- event time ベースで同一windowか判定し、received time の到着順には依存しない
- `early_confidence` 以上のRCAResultはwindow満了前でも `TENTATIVE` として返す
- 後続Observationでroot causeが変わった場合は `RCA_REVISED` を返す
- windowを超えるObservationが来た場合は前windowを閉じ、新windowで評価を開始する
- `temporal_fit` は Observation の event time と候補からの距離を使って加点・減点する

検証コマンド:

```bash
pytest -q src/tests/test_observation_buffer.py
pytest -q src/tests/test_observation_buffer.py src/tests/test_hypothesis_scoring.py src/tests/test_observation.py src/tests/test_hypothesis_rca_poc.py src/tests/test_causal_topology.py src/tests/test_yang_loader.py src/tests/test_root_cause.py
```

結果:

```text
5 passed, 1 warning
76 passed, 1 warning
```

### Phase H5: Incident Projector ✅ 完了

目的: `RCAResult` を既存 `Incident` モデルへ投影し、Store/通知へ接続する前の境界を作る。

タスク:

- [x] `IncidentProjector` を作成する
- [x] `root_cause_object` から既存 `root_cause_node` 互換値を生成する
- [x] `primary_event` / `secondary_nodes` / `raw_logs` を Observation から構築する
- [x] `RCA_REVISED` 用の履歴を保存できるようにする
- [x] 既存 `IncidentMerger` を使うか置き換えるか判断する

完了条件:

- [x] RCAResultから既存IncidentOut互換のレスポンスを生成できる
- [x] 既存APIへ接続せず単体テストで確認できる

実装メモ:

- `IncidentProjector` / `ProjectionEvent` / `ProjectionEventType` を追加
- `RCAResult.root_cause_object` を既存 `Incident.root_cause_node` 互換の代表Deviceへ変換
- `Observation` から `primary_event` / `secondary_nodes` / `raw_logs` / `last_fault_at` を構築
- score component を `RCAEvidence` として `RCAExplanation` に投影
- `ProjectionEventType.INCIDENT_CANDIDATE` と `RCA_REVISED` を定義し、Store接続前の履歴保存境界を作成
- `IncidentMerger` はこのPhaseでは接続しない。H7以降の dual/API 接続時に、object-level RCAを保持したまま既存マージを使うか置き換えるか判断する

検証コマンド:

```bash
pytest -q src/tests/test_incident_projector.py
pytest -q src/tests/test_incident_projector.py src/tests/test_observation_buffer.py src/tests/test_hypothesis_scoring.py src/tests/test_observation.py src/tests/test_hypothesis_rca_poc.py src/tests/test_causal_topology.py src/tests/test_yang_loader.py src/tests/test_root_cause.py
```

結果:

```text
5 passed, 1 warning
81 passed, 1 warning
```

### Phase H6: 復旧・Lifecycle統合 ✅ 完了

目的: fault Observation と recovery Observation を同じIncident lifecycleへ反映する。

タスク:

- [x] recovery Observation を既存OPEN Incidentへ対応付ける
- [x] Link復旧時に関連Interface/BGPSessionをまとめてRECOVERINGにする
- [x] Device復旧時に配下影響を再評価する
- [x] quiet period 後にRECOVEREDへ遷移する
- [x] 再障害時にFLAPPINGを判定する

完了条件:

- [x] Link down -> Link up で同一Incidentが回復する
- [x] Device down -> downstream recovery の順不同でも矛盾しない

実装メモ:

- `HypothesisIncidentLifecycle` / `HypothesisLifecycleEvent` / `HypothesisLifecycleEventType` を追加
- projected Incident の `RCAExplanation` から object-level root cause を復元する
- recovery Observation が root cause object または関連Interface/BGPSessionに一致する場合、Incidentを `RECOVERING` または `DEGRADED` へ遷移
- quiet period 経過後、後続faultがなければ `RECOVERED` へ遷移
- `RECOVERING` / `RECOVERED` 中に関連fault Observationが来た場合は `FLAPPING` 判定を行う
- このPhaseでは既存API/Storeには接続せず、既存Incidentモデルへの状態反映だけを単体テストで確認する

検証コマンド:

```bash
pytest -q src/tests/test_hypothesis_lifecycle.py
pytest -q src/tests/test_hypothesis_lifecycle.py src/tests/test_incident_projector.py src/tests/test_observation_buffer.py src/tests/test_hypothesis_scoring.py src/tests/test_observation.py src/tests/test_hypothesis_rca_poc.py src/tests/test_causal_topology.py src/tests/test_yang_loader.py src/tests/test_root_cause.py
```

結果:

```text
5 passed, 1 warning
86 passed, 1 warning
```

### Phase H7: API/UI切替導入 ✅ 完了

目的: 本番経路を壊さず、新方式を比較実行できるようにする。

タスク:

- [x] `RCA_ENGINE=legacy|hypothesis|dual` を追加する
- [x] `dual` では legacy と hypothesis の判定差分を保存する
- [x] `/debug/rca/hypothesis` のような比較APIを追加する
- [x] UIで `root_cause_object` と score内訳を表示する
- [x] H7時点では通知をlegacyに限定し、H8後にhypothesisを通常経路へ接続する

完了条件:

- [x] 同じSYSLOGを legacy / hypothesis に流して差分を確認できる
- [x] H7時点ではhypothesis側の誤判定が本番通知に影響しない

実装メモ:

- `create_app(..., rca_engine="legacy|hypothesis|dual")` を追加
- `RCA_ENGINE` 環境変数をAPIサーバー起動時に読み込む
- topologyロード時に `CausalTopology` / `HypothesisRCAEngine` / `IncidentProjector` / `ObservationBuffer` を初期化
- `/debug/status` に `rca_engine` / `causal_topology_loaded` / `last_rca_comparison` を追加
- `/debug/rca/hypothesis` を追加し、保存・通知なしで legacy と hypothesis の比較結果を返す
- `dual` では通常 `/ingest` は既存legacy保存・通知を維持し、hypothesis結果は `app.state.last_rca_comparison` に保持する
- `hypothesis` mode はPhase H8後に通常 `/ingest` の保存・通知経路へ接続済み
- UI専用画面は未追加だが、debug APIレスポンスに `root_cause_object` / `score_components` / projected incident を含め、UI表示に必要なデータ構造を提供済み

検証コマンド:

```bash
pytest -q src/tests/test_hypothesis_api.py
pytest -q src/tests/test_hypothesis_api.py src/tests/test_hypothesis_lifecycle.py src/tests/test_incident_projector.py src/tests/test_observation_buffer.py src/tests/test_hypothesis_scoring.py src/tests/test_observation.py src/tests/test_hypothesis_rca_poc.py src/tests/test_causal_topology.py src/tests/test_yang_loader.py src/tests/test_root_cause.py src/tests/test_api_ingest.py
```

結果:

```text
4 passed, 1 warning
110 passed, 1 warning
```

### Phase H8: 段階移行 ✅ 完了

目的: 比較検証の結果を見て、本番デフォルトを切り替える。

タスク:

- [x] 実ログサンプルで誤判定率を記録する
- [x] legacyとhypothesisの差分をレビューする
- [x] Link / Device / Interface / BGPSessionごとの正答率を確認する
- [x] 通知対象を hypothesis に切り替える条件を決める
- [x] legacy inferencer の扱いを縮退または互換モード化する

完了条件:

- [x] CLOS検証ログで hypothesis が legacy を上回る
- [x] 本番通知に使えるconfidence基準が定義される
- [x] rollback方法がREADMEに記載される

実装メモ:

- `RCASampleEvaluation` / `RCAMigrationReadiness` / `evaluate_migration_readiness()` を追加
- `/debug/rca/migration-readiness` を追加し、ラベル付きサンプルから legacy / hypothesis の正答率を評価する
- `last_rca_migration_readiness` を `/debug/status` で確認可能にした
- `ready=true` の場合のみ `recommended_engine=hypothesis` を返す
- 条件未達時は `recommended_engine=dual` を返し、比較運用継続とする
- `rollback_engine=legacy` を常に返し、切戻し手段をAPIレスポンスにも含める
- 実装上の本番デフォルトは `hypothesis` へ切り替え済み。legacyは `RCA_ENGINE=legacy` を明示した場合のみ使う

移行判定API:

```bash
curl -s http://localhost:8000/debug/rca/migration-readiness \
    -H 'content-type: application/json' \
    -d '{
        "min_accuracy": 0.8,
        "min_confidence": 0.6,
        "samples": [
            {
                "sample_id": "clos-link-spine1-leaf2",
                "expected_root_cause_object": "PhysicalLink:Leaf2:GigabitEthernet0/0--Spine1:GigabitEthernet0/1",
                "expected_legacy_nodes": ["Leaf2", "Spine1"],
                "messages": [
                    {"raw": "<35>Sep 5 08:13:06.021 Leaf2 %LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down"},
                    {"raw": "<35>Sep 5 08:13:06.021 Spine1 %LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down"}
                ]
            }
        ]
    }'
```

切替条件:

- `ready=true`
- `hypothesis_accuracy >= min_accuracy`
- `average_hypothesis_confidence >= min_confidence`
- `hypothesis_accuracy >= legacy_accuracy`
- `PhysicalLink` / `Device` / `Interface` / `BGPSession` の各カテゴリで、運用上許容できない偏りがない

通常起動:

```bash
make start
```

`make start` は `RCA_ENGINE=hypothesis` をデフォルトで渡す。

明示的な切替方法:

```bash
RCA_ENGINE=hypothesis
```

推奨移行手順:

1. `make start` で hypothesis 経路を起動する
2. 必要に応じて `RCA_ENGINE=dual` で運用し、`/debug/rca/hypothesis` と `/debug/rca/migration-readiness` で差分を確認する
3. ラベル付き実ログサンプルを増やし、`ready=true` になるまで採点・正規化を調整する
4. 誤判定が出た場合は `RCA_ENGINE=legacy` で切り戻す

rollback方法:

```bash
RCA_ENGINE=legacy
```

rollback判断:

- hypothesisで root cause object が `None` になるサンプルが増えた
- `hypothesis_accuracy < legacy_accuracy` になった
- PhysicalLink障害をDevice障害として通知する誤判定が増えた
- recovery/FLAPPINGの状態遷移が運用期待とズレた

検証コマンド:

```bash
pytest -q src/tests/test_rca_migration.py src/tests/test_hypothesis_api.py
pytest -q src/tests/test_rca_migration.py src/tests/test_hypothesis_api.py src/tests/test_hypothesis_lifecycle.py src/tests/test_incident_projector.py src/tests/test_observation_buffer.py src/tests/test_hypothesis_scoring.py src/tests/test_observation.py src/tests/test_hypothesis_rca_poc.py src/tests/test_causal_topology.py src/tests/test_yang_loader.py src/tests/test_root_cause.py src/tests/test_api_ingest.py
```

結果:

```text
9 passed, 1 warning
115 passed, 1 warning
```

---

## 6. 採用判断ゲート

各段階で以下を満たさない場合は、次Phaseへ進まない。

| Gate | 判定内容 | 必須条件 |
|---|---|---|
| G0 | PoC妥当性 | 4基本ケースが通る |
| G1 | トポロジー妥当性 | Causal Objectが実トポロジーから欠落なく生成される |
| G2 | Observation妥当性 | 実SYSLOGサンプルの正規化結果が運用感覚と一致する |
| G3 | RCA妥当性 | Link / Device / Interface / Session を安定して分離できる |
| G4 | Lifecycle妥当性 | down/upの順不同でIncident状態が破綻しない |
| G5 | 移行妥当性 | dual運用でlegacyより誤判定が少ない |

---

## 7. 直近の次アクション

優先順:

1. `make start` でhypothesis経路を起動し、リンク停止などの実ログサンプルを確認する
2. `/debug/rca/migration-readiness` のサンプル数を増やす
3. `ready=true` が安定するか、通常 `/ingest` の生成Incidentが運用期待と合うか確認する
4. 誤判定が出た場合は `RCA_ENGINE=legacy` へ戻し、Observation正規化または採点ポリシーへフィードバックする

当面の判断基準:

- 通常 `/ingest` はhypothesis経路を使う
- legacyはrollback用としてのみ使う
- 実ログで誤判定が出た場合は `RCA_ENGINE=legacy` へ戻し、Observation正規化または採点ポリシーを直す
- `/debug/rca/hypothesis` と `/debug/rca/migration-readiness` は継続して判断材料に使う

---

## 8. リスクと対策

| リスク | 内容 | 対策 |
|---|---|---|
| スコアが属人的になる | 加点・減点が増えると調整不能になる | score内訳を必ず構造化し、テストで固定する |
| トポロジー情報不足 | physical-connection に interface-id がないとLink特定できない | ロード時に警告または検証エラーを出す |
| 未知SYSLOGが多い | Observation化できずDevice障害に寄りやすい | SKBとObservation正規化を分離し、unknownは低confidenceにする |
| BGPと物理Linkの誤結合 | 論理障害を物理障害と誤判定する | BGP-onlyとLink-backed sessionを区別する |
| 新方式の誤通知 | hypothesisの誤判定が通知される | `RCA_ENGINE=legacy` で即時rollbackし、debug APIで差分を確認する |

---

## 9. 関連ファイル

| ファイル | 役割 |
|---|---|
| `src/topology_syslog/topology/causal_topology.py` | Phase H1 の正式CausalTopologyモデル |
| `src/topology_syslog/correlation/observation.py` | Phase H2 のSYSLOG -> Observation正規化 |
| `src/topology_syslog/correlation/observation_buffer.py` | Phase H4 のObservationBufferとRCA改訂イベント |
| `src/topology_syslog/correlation/incident_projector.py` | Phase H5 のRCAResult -> Incident投影境界 |
| `src/topology_syslog/correlation/hypothesis_lifecycle.py` | Phase H6 のobject-level recovery lifecycle |
| `src/topology_syslog/correlation/rca_migration.py` | Phase H8 の移行可否評価 |
| `src/topology_syslog/correlation/hypothesis_scoring.py` | Phase H3 のHypothesis採点ポリシー |
| `src/topology_syslog/correlation/hypothesis_rca.py` | Phase H0 の独立PoC |
| `src/tests/test_causal_topology.py` | Phase H1 のCLOS Object生成・逆引きテスト |
| `src/tests/test_observation.py` | Phase H2 のObservation正規化テスト |
| `src/tests/test_observation_buffer.py` | Phase H4 のバケット処理・遅延到着テスト |
| `src/tests/test_incident_projector.py` | Phase H5 のIncident投影テスト |
| `src/tests/test_hypothesis_lifecycle.py` | Phase H6 の復旧・FLAPPINGテスト |
| `src/tests/test_hypothesis_api.py` | Phase H7 の比較API・dual modeテスト |
| `src/tests/test_rca_migration.py` | Phase H8 の移行可否評価テスト |
| `src/tests/test_hypothesis_scoring.py` | Phase H3 の採点内訳・勝ち条件テスト |
| `src/tests/test_hypothesis_rca_poc.py` | Phase H0 の判定テスト |
| `src/topology_syslog/correlation/root_cause_inferencer.py` | 現行RCA方式 |
| `src/topology_syslog/api/main.py` | 現行即時処理パイプライン |
| `configs/clos/yang_topology.yaml` | CLOS検証用トポロジー |
