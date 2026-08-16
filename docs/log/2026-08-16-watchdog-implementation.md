# watchdog Lambdaの実装(フェーズ9着手)

## 背景

Namazu(nna774/NamazuHaUrokoGaNai)の`lambda/watchdog/`を参考にしてElectabuzzにも
実装したい、という要望を受けて着手した。2026-08-12のAC入力断検知実装の時点で
「Slack等の外部通知はfirmwareから直接叩かず、地震計の生存台帳+watchdog Lambdaと
同じパターンでクラウド側detect(フェーズ9、まだ何も無い)に委ねる」という設計判断は
既にしてあったので(→ [2026-08-15-ac-input-disconnect-detection-impl.md](2026-08-15-ac-input-disconnect-detection-impl.md))、
これはその積み残しを埋める作業でもある。

## 現状の棚卸し(着手前)

Namazu側を読み直して分かったのは、Electabuzzは思ったより手前まで出来ていたこと:
生存台帳(`electabuzz-devices`)・`lambda/ingest/handler.py`の`_record_liveness()`・
`lambda/api/handler.py`の`/devices`は2026-08-12時点で既に実装済み(→
[2026-08-12-dashboard-device-status.md](2026-08-12-dashboard-device-status.md))。
**無かったのはwatchdog Lambda本体だけ**——欠測・遅延を検知しても誰にも言わない
状態だった。

一方でElectabuzzにはNamazuに無い固有事情がある:
- **AC入力断(`kGfrqFlagPowerFail`)**: 2026-08-15に検知ロジック・LED通知まで実装済みで、
  クラウド側の通知だけが未実装だった
- **`lambda/common/`ディレクトリ自体が無かった**: Namazuの`watchdog_mute.py`・
  `ota_watch.py`・`device_meta.py`に相当する置き場が無い

## 決めたこと

### スコープ: 欠測/遅延に加えてAC入力断・再起動検知・OTA停滞まで一括で実装する

ユーザーから「全部できるといい」との指示を受け、Namazuとの機能パリティ
(欠測・データ遅延・OTA停滞)に加え、Electabuzz固有のAC入力断・再起動検知も
同じフェーズで実装した。OTA停滞検知(`ota_watch.py`)はNamazuからほぼ無改造で
移植できると分かっていたので、労力対効果が高く含めることにした。

### AC入力断は「線が抜けたか停電したか」を区別しない

これは2026-08-12の既存判断(→ [2026-08-12-afe-input-disconnect-detection.md](2026-08-12-afe-input-disconnect-detection.md))
をそのまま踏襲。AFE単体の信号では原理的に区別できないので、watchdog側でも
無理に判別しようとしない。バッチの`flags`(`kGfrqFlagPowerFail`、バッチ単位)を
そのまま生存台帳へ反映し(`lambda/common/power_fail_watch.py`)、
`batch_uplink.devices.evaluate_lag()`と同じ形の状態遷移(初回通知→再送→復帰)で
Slackへ通知する。**欠測中は黙る**——データが来ていないのに古いpower_fail状態
だけで通知し続けるのを防ぐガードも、`evaluate_lag`から踏襲した。

### 再起動検知は記録のNamazuの体裁を保ちつつ、Electabuzzでは通知まで踏み込む

Namazuの`device_meta.py`(`boot_epoch_us`の逆算・記録)はAPI/ダッシュボード表示用で、
Slack通知はしていない——OTAでの正常な再起動が頻繁にあるため、毎回通知すると
ノイズになる、という判断だったと推測される。

Electabuzzは事情が違う: pull型OTAは`tools/request_ota.py`の**手動許可**でしか
動かないので、それを経ない再起動は稀であり、かつWDTパニック等の異常を示す
可能性がある(Namazu側の実例 → [2026-08-08-wdt-panic-hypothesis.md](2026-08-08-wdt-panic-hypothesis.md)
と同種の懸念)。そのため`lambda/common/reboot_watch.py`を新規に書き、
watchdogが再起動のたび1回だけ(再送はしない)Slack通知するようにした。
`X-Elbz-Reset-Reason`相当のヘッダはfirmware側が未対応なので、Namazuと違い
`reset_reason`は持たない——これは今回のスコープ外(firmware変更が要るため)。

再起動検知の状態遷移は「初回観測(baseline)は基準を作るだけで通知しない」設計に
した。監視を始めた瞬間に「起動していた」ことを再起動と誤認しないためで、
`evaluate_reboot()`が`boot_epoch_notified_us`(watchdogが前回見た値)との差分だけを
見る形にしてある。

### Slackメンションは「見落とすと実害が大きいもの」だけに付ける

Namazuのwatchdogは全通知にメンションを付けているが、Electabuzzでは
欠測・データ遅延・AC入力断(いずれも「今まさに異常が起きている」)にだけ付け、
再起動検知・OTA停滞(情報寄り)には付けないことにした。メンション先の
SlackユーザーIDはterraform変数`slack_mention`の既定値として、Namazuと同じ
値(`<@U0323ESK6>`、同一ワークスペース)を入れてある——空文字にすれば無効化できる。

### mute機構も移植する(実機1台構成だが将来に備える)

`lambda/common/watchdog_mute.py` + `tools/mute_device.py`をNamazuからほぼ
無改造で移植した。実機は1台のみで今すぐ使う場面は無いが、Namazu側の実装が
そのまま使える形だったので、将来の試験機・退役に備えて先に入れておく判断にした
(「簡単にできるならやる」という指示を受けての判断)。

## 実装した変更

- **`lambda/common/`を新設**: `power_fail_watch.py`(新規)・`reboot_watch.py`(新規)・
  `watchdog_mute.py`(Namazuから移植)・`ota_watch.py`(Namazuから移植、
  `reached_target`/`clear_ota_target`は既存の`lambda/ota_target.py`と重複するので
  持ち込んでいない)
- **`lambda/watchdog/handler.py`を新規実装**: Namazuの構成を踏襲しつつ、
  AC入力断・再起動検知を追加
- **`lambda/ingest/handler.py`を拡張**: 毎バッチ`power_fail`・`boot_epoch_us`を
  生存台帳へ反映し、`watchdog_muted`を無条件で解除する呼び出しを追加
  (いずれも主経路ではない——失敗してもバッチ保存自体は成功扱い、という
  既存の`_record_liveness`と同じ方針を踏襲)
- **`tools/mute_device.py`を新規**: Namazuからの移植
- **terraform**: `variables.tf`(しきい値・Slack設定10個)、`main.tf`(`local.watchdog_env`)、
  `lambda.tf`(watchdog Lambda + EventBridgeルール + permission)、
  `build_lambda.sh`(watchdogのビルド、ingestへの`common/`同梱を追加)
- **`terraform.tfvars`に`slack_webhook_url`を設定**(ユーザー提供のIncoming Webhook URL。
  gitignore対象なのでこのworktreeにしか無い——`secrets.h`と同じ既存の運用パターン。
  **本体の作業ツリーへ手でコピーが要る**)

## 検証したこと

- `.venv/bin/python -m pytest lambda/tests`: 101件全パス(新規: 
  `test_power_fail_watch.py`・`test_reboot_watch.py`・`test_watchdog_mute.py`・
  `test_ota_watch.py`・`test_watchdog.py`、既存`test_ingest.py`に9ケース追加)
- `terraform/build_lambda.sh`: ingest/api/watchdogの3zip生成に成功。
  watchdog.zipを実際に展開してimportが通ることも確認した
- `terraform validate`: 緑(`terraform init -backend=false`でprovider解決のみ)
- `terraform fmt`: 適用済み

## まだやっていないこと

- **`terraform apply`はまだ実行していない**(費用が生じる操作なので明示の許可が要る)
- **実機での動作確認はまだ**——AC入力線を実際に抜く・デバイスを止める等で
  Slack通知が実際に飛ぶかどうかは、applyしてからでないと見られない
- `reset_reason`ヘッダの追加(firmware側の変更が要るため、今回のスコープ外)
