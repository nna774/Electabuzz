# 2026-09-01 measurementTask分割(PR #91)をOTAで実機に配信、稼働確認まで完了

## 経緯

[log/2026-09-01-cycles-jump-wifi-reconnect-correlation.md](2026-09-01-cycles-jump-wifi-reconnect-correlation.md)
で実装したcyclesジャンプ対策(PR #91)を、ユーザーの「mergeしてOTAかけて」の
指示で反映した。

## やったこと

- PR #91を`main`へマージ(`gh pr merge 91 --merge`、マージコミット`3d87157`)
- クリーンな`main`(`3d87157`)から`.venv/bin/pio run -d firmware -e record`で
  ビルド。**`tools/publish_ota.sh`はこのworktreeに`.venv`が無く
  `$HOME/.platformio/penv/bin/pio`にフォールバックした結果`intelhex`モジュール
  不足で失敗したため、スクリプトの手順(ビルド→sha256→S3公開)を手動で再現した**
  ——本体worktreeの`.venv/bin/pio`を明示指定すれば動く(ユーザーからも
  「pioはvenvの中にある」と念押しされていた)
- `s3://electabuzz-dashboard-486414336274/ota/record/3d87157.bin`
  (+`.sha256`)へ公開
- `.venv/bin/python tools/request_ota.py request 1 3d87157 --yes`で
  device 1に配信を許可(直前のfw_versionは`21a6a45`)
- `tools/request_ota.py list`をポーリングし、約数分で`pending_ota_version`が
  自動解放される(=達成)ことを確認
- `/devices`を直接curlし、`fw_version: "3d87157"`・`pending_ota_version: null`を
  確認。`/recent`でも`session_id`が28→29に進み(OTA再起動を反映)、
  `timebase_source: "PPS"`・`tb_residual_ns: 8`・`freq_hz: 50.010071`と
  正常な値で送信が継続していることを確認した

## 状態

**PR #91は`main`にマージ済み、実機device 1は`3d87157`(measurementTask分割版)で
稼働中。** 再起動後、PPSロックも問題なく再確立できている。

**残る確認**: 実際のWiFi遮断が起きた時に`gWindowQueue`が溢れなくなった
(=350Hz/100Hzスパイクが再発しない)ことは、今後の実際のWiFi断イベント待ち
——今回のOTAデプロイ自体は正常系の動作確認に留まる。
