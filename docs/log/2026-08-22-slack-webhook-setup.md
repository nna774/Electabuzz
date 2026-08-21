# Slack webhookが未設定だったのに気づき、設定した

## 発端

[周波数逸脱イベント多発の調査](2026-08-20-dashboard-event-time-hash-routing.md)の続きで、
「detectのしきい値を上げるべきか」を検討していたところ、そもそも通知が実際に飛んでいるか
確認していないことに気づいた。

## わかったこと

`electabuzz-detect`・`electabuzz-watchdog`両Lambdaの実際の環境変数を直接見たところ、
**`NAMZ_SLACK_WEBHOOK_URL`がどちらも空文字だった**（最終更新はいずれも2026-08-16、
watchdog実装apply時点）。`batch_uplink.notify.from_env()`は空ならNullNotifierになる
仕様(→ docs/cloud.md)なので、**watchdog・detectとも実装・applyは完了していたが、
Slack通知は運用開始時から一度も実際には送られていなかった**——`terraform.tfvars`の
`slack_webhook_url`(`default = ""`)がどのworktreeでも埋まっていなかったのが原因。

watchdogは「見落とすと実害が大きい」欠測・AC入力断等の通知を担う要石なので、
検知ロジック自体が正しくてもここが死んでいれば実質機能していないのと同じだった。

## 対応

ユーザーから渡されたwebhook URLを、本体チェックアウト(`/Users/nana/codes/Electabuzz/terraform/terraform.tfvars`、
gitignore対象)を基にこのworktreeの`terraform.tfvars`へ追記し、`terraform apply`
(0 add / 2 change / 0 destroy、detect・watchdogの環境変数更新のみ)で反映した。
値そのものは会話・コマンドいずれにも出力せず、ファイル経由でのみ扱った。

反映後、webhook URLへ直接テストPOSTを送り`200 ok`を確認、実際にSlackへ届くことも
ユーザー側で確認できた。**通知経路は現在生きている。**

## 次に何が可能になったか

detectの周波数逸脱閾値(`freq_deviation_threshold_hz`、既定100mHz)が
[実データで見ると1日数件のペースで発火する](2026-08-20-dashboard-event-time-hash-routing.md)
状態のまま、今後は実際にSlackへ通知が飛ぶようになる。**閾値は一旦このまま様子見と
判断した**——実際の通知頻度が本当に鬱陶しいかどうかを見てから閾値調整するかを
決める、という順序にした(先に閾値を絞ってデータを失うより、まず実運用で様子を
見る方を優先)。校正自体は`docs/progress.md`の未着手タスクとして残る。
