# 2026-11-19 detectの通知過多修正をapplyした

## 経緯

[2026-11-19-detect-notification-flood.md](2026-11-19-detect-notification-flood.md)(PR #99)を
ユーザーの「Merge and apply」の指示でマージし、反映した。

## やったこと

- `terraform plan`: 0 add / 4 change / 0 destroy。detectに環境変数
  `ELBZ_VOLTAGE_DETECT_ENABLED=0`・`ELBZ_FREQ_PLAUSIBLE_DEV_HZ=5`が増えるのは想定通り。
  ingest・watchdogのコードハッシュも変わったが、zipに`lambda/common/`が丸ごと同梱される
  ためで、両者のコード自体は前回デプロイ(2026-10-10)から変わっていない
- applyはworktreeをorigin/mainに合わせ、`terraform.tfvars`をメインチェックアウトから
  コピーして行った(メインチェックアウトは別ブランチで作業中だったため触らない)

## 実クラウドで確かめたこと

- detectの環境変数が反映されている(`get-function-configuration`)
- 最新バッチでdetectを手動起動(`--log-type Tail`)し、`detect error`が出ないこと
- 本番テーブルに対してローカルから`_latest_event`を実行し、周波数逸脱・RoCoFの
  ポインタが最新イベントを指して作られること、2回目はポインタ経由で引けること。
  電圧異常は判定を止めたのでポインタを作っていない
- `/events`が`last_us`降順で返ること(修正前は1000件ページ内の任意の50件だった)
- apply後に電圧異常の新規・延長が出ていないこと

`electabuzz-admin`ロールにはCloudWatch Logs・メトリクスの読み取り権限が無いため、
detectの実行ログは`invoke --log-type Tail`でしか見ていない。

## 状態 / 残り

- 周波数逸脱が継続したときに再通知されないことは、次に実際の逸脱が起きるまで未確認

## 偽の電圧異常を削除した

ユーザーの指示で、`electabuzz-events`の電圧異常6553件(2026-08-31〜11-19 18:30)を全て
削除した。校正が狂った`v_rms_mv`による偽物で、`/events`・ダッシュボードを埋めていた。
校正の狂いが始まった時期は調べていないので、本物が混じっていた可能性は否定できないが、
判定の基準そのものが信用できない以上、区別のしようが無い。周波数逸脱462件・RoCoF 7件・
ポインタ2件は残した(RoCoFの偽物5件は件数が少なく実害が無いので消していない)。
