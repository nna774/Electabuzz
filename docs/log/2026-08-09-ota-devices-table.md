# OTAの配信対象をterraform変数からDynamoDB(デバイス生存台帳)へ切り替えた

## 何を決めたか、なぜそう決めたか

[docs/log/2026-08-09-ota-implementation.md](2026-08-09-ota-implementation.md)で
実装したOTAは、配信対象バージョンをterraformの環境変数(`ota_target_version`)で
持つ設計にした——Namazuの`pending_ota_version`(DynamoDB)+watchdog停滞検知は
複数台の無人運用向けで、Electabuzzは実機1台・watchdog自体が無いので過剰と
判断したため（→ 同ログ「トリガー: DynamoDB方式ではなくterraform環境変数+
バッチ送信便乗」）。

[docs/log/2026-08-09-ota-pull-live-test.md](2026-08-09-ota-pull-live-test.md)で
実際にこの方式を1回動かし(`351cd38`への配信)、取得〜書き込み〜再起動まで
成功したが、その直後にユーザーから「terraform applyでやるの大袈裟だし、
DynamoDBに書けないかな。どうせダッシュボードで現在の版とかの情報見たいし」
という指摘があった。

再検討して**DynamoDB方式に切り替えた**。判断が変わった理由:

1. **配信のたびにterraform applyは重い。** state lock・plan生成・実行で
   数十秒かかり、AWS認証情報がローカルに要る。DynamoDBへの1項目更新は
   即座に終わる軽い操作
2. **ダッシュボードでの版数表示という別の要望も同時に満たせる。** `/devices`
   エンドポイントを作るにはどのみち生存台帳(DynamoDB)が要る。1つのテーブルで
   両方の要件を満たせるなら、別々の仕組みを維持するより安い
3. **「存在しない要件への一般化はしない」という当初の判断は誤りではなかった。**
   OTA単体では複数台ロールアウト・watchdog連携という重い機能は要らないという
   判断は今も正しい。今回作ったのは**Namazuの`pending_ota_version`と同じ
   キー・バリューを持つテーブル**であって、watchdog連携・停滞検知・段階的
   ロールアウトの管理機能は依然として作っていない——スコープはそのまま、
   単に**置き場所**をterraform変数からDynamoDBに変えただけ

## 実装した内容

- `terraform/devices.tf`: `aws_dynamodb_table.devices`(PAY_PER_REQUEST、
  hash_key `device_id`)を新設
- `terraform/iam.tf`: ingest/api共有ロールにDynamoDBの
  GetItem/PutItem/UpdateItem/Scan権限を追加
- `terraform/main.tf`: `NAMZ_DEVICES_TABLE`環境変数をingest/api両方に配線
  （`batch_uplink.devices`が期待する変数名。Namazu由来のまま、値だけ
  Electabuzzのテーブルを渡す——`NAMZ_HMAC_SECRET`と同じ理由）
- `terraform/variables.tf`: `ota_target_version`変数を削除
- `lambda/ota_target.py`(新規): `pending_ota_version`の達成検知・解放。
  Namazuの`lambda/common/ota_watch.py`から停滞検知(時間経過ベースの
  再通知)を除いた最小版
- `lambda/ingest/handler.py`: `_record_liveness`が`X-Elbz-Fw-Version`
  ヘッダを`devices.record_batch(..., fw_version=...)`に渡すよう変更。
  `_ota_headers()`(env var読み)を`_ota_response_headers(device_id)`
  (DynamoDB読み書き)に置き換え
- `lambda/api/handler.py`: `/devices`エンドポイントを追加
  (device_id・fw_version・last_ingest_at_us・staleness_s・batches_total・
  pending_ota_version)
- `dashboard/app.js`: `/devices`を取得し、品質テーブルに「ビルド版数」
  「OTA」行を追加（補助情報として——取得失敗してもメインのグラフ表示は
  妨げない設計にした）
- `tools/request_ota.py`(新規)・`tools/awsenv.py`(新規): Namazuの
  同名ツールを移植。`request`/`cancel`/`list`
- `tools/publish_ota.sh`: 配信手順の案内をterraform.tfvars編集から
  `request_ota.py`呼び出しに変更

## 何が覆ったか

`docs/ota.md`§3を全面的に書き換えた。「DynamoDB・watchdogは使わない」という
見出しと理由づけを削除し、Namazuと同じDynamoDB方式に差し替えた。旧方式で
1回実機確認した記録([2026-08-09-ota-pull-live-test.md](2026-08-09-ota-pull-live-test.md))
は経緯として残し、本体からは新方式の説明に統一した。

## 次に何が可能になったか

実際にDynamoDBへ書き込まれること・`/devices`が値を返すことを実機バッチ送信で
確認済み（`fw_version=351cd38`が台帳に記録され、`/devices`のレスポンスにも
現れた）。新方式でのpull型OTA本体(配信〜取得〜再起動)の確認はこの後行う。
