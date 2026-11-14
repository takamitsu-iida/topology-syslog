# マシンラーニング

## Step 0. 障害時でも必ずSYSLOGを受信できるように管理ネットワークを外だしにする

## Step 1. CMLでの障害自動注入とSYSLOGデータ収集（最優先）

virl2_client を使い、ノード障害・リンク障害をランダムに発生させて「Syslog群」と「正解ノード（Ground Truth）」のペアデータを1,000件ほど自動収集する。

このときに受信したSYSLOGに関しては、全てSKBに入れるようにする。

## Step 2: 評価指標（Baseline）の作成

収集したデータに対し、現在の方式で正解率（Accuracy / Precision / Recall）が何%なのかを定量化する。

## Step 3: 簡単な tabular ML モデル（LightGBM / Random Forest）の適用

各ノードごとに「受信ログ数」「直接エラー数」「配下ノードのエラー数」「トポロジー階層」を特徴量（Feature）として抽出し、分類モデルを作成する。

## Step 4: GNN へのステップアップ

複雑な網状トポロジー（Mesh Network）やマルチホーム構成で精度が落ちる場合に、PyTorch Geometric等を用いて本格的なGNNモデルへと刷新する。
