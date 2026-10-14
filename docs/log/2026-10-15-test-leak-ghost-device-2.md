# 2026-10-15 存在しないdevice 0002の欠測通知（テストから本番DynamoDBへの書き込み漏れ）

## 何が起きたか

watchdogから「device 0002 から 20740日 データが来ていない」（最終受信:記録なし）という
「デバイス欠測（継続）」通知が来た。device 2は存在せず、20740日は1970年からの日数。

`electabuzz-devices`の`device_id=2`の行は`power_fail=false`とwatchdogが書いた
`offline_notified_at_us`だけで、`last_ingest_at_us`が無かった。このため経過時間は
最終受信0扱いで計算されていた。

## 原因

`device_id=2`はテスト用golden(`testdata/gfrq_v1_golden.hex`)の値。
`lambda/tests/test_ingest.py`のいくつかのテストは`NAMZ_DEVICES_TABLE`に本番と同じ
`electabuzz-devices`を入れ、`devices.record_batch`など一部の関数だけを差し替えていた。
差し替えていない`power_fail_watch.record`・`watchdog_mute.clear_mute`は本物の
UpdateItemを発行する。repo直下の`.envrc`(`AWS_PROFILE=electabuzz-admin`)が効いた
シェルでpytestを回すと、本番テーブルへ書き込まれる。UpdateItemは対象行が無ければ作るので、
キーと`power_fail`だけを持つ幽霊行ができた。

## 何を決めたか

- **テストからAWSへ届く経路を、テストごとの差し替えではなく`conftest.py`のautouse fixture
  (`_no_real_aws`)で一律に断つ。** 認証情報系の環境変数を外してダミー鍵を入れ、
  `AWS_ENDPOINT_URL=http://127.0.0.1:9`・`AWS_MAX_ATTEMPTS=1`にする。
  - 個々のテストの差し替え漏れを埋める方針は採らない。関数を足すたびに同じ漏れが再発するからだ。
  - ダミー鍵だけで済ませる方針も採らない。それでは本物のAWSへのリクエスト自体は飛ぶ。
    接続拒否にしておけば、ネットワークの有無に関係なく即座に失敗し、
    各`_record_*`の例外握りつぶしで静かに終わる。
- 幽霊行(`device_id=2`)は手で削除した。

## 確認

`AWS_PROFILE=electabuzz-admin`を付けたまま`pytest lambda/tests`(148件全パス)を回し、
その後`device_id=2`の`get-item`が空であることを確認した。
