# TE絶対値表示を`apply`し、実クラウドで動作確認する

[前段の実装](2026-08-17-te-absolute-display-design.md)(PR #66)をマージ後、
`terraform apply`して実クラウドで確認した。

## apply

マージ後にこのworktreeを`origin/main`へ合わせ(他セッションの`detect`実クラウド
確認・ダッシュボードのイベント表示分もまとめて取り込まれた)、`build_lambda.sh`で
zipを作り直してから`terraform plan`を取り直した。

`plan`は**1 add(`electabuzz-te-anchors`テーブル)/5 change(IAMポリシーへの
`TeAnchors`ステートメント追加、Lambda4本の再デプロイ)/0 destroy**。再デプロイが
ingest/api以外(detect/watchdog)にも及ぶのは`common/`同梱に伴う既存の挙動で
(→ [log/2026-08-16-watchdog-implementation.md](2026-08-16-watchdog-implementation.md)
と同じ理由)、破壊的変更は無い。そのまま`apply`し、1 added/5 changed/0 destroyedで完了した。

## 実クラウド確認

`/recent`を直接叩いて確認した。

```
$ curl -s "https://api.electabuzz.dark-kuins.net/recent?minutes=2"
```

`latest`に`te_seconds: -0.020565`が乗り、`timebase_source: "PPS_NTP"`・
`session_id: 27`・`device_id: 1`と一致していた。`te_seconds`の系列も
単調に(この時点では)減っていく実データらしい形になっていた。

DynamoDBの`electabuzz-te-anchors`を直接scanしても、実際にアンカー行が
1件書き込まれていることを確認した:

```
anchor_id=0001-27-1786910208389848, device_id=1, session_id=27,
t0_us=1786910208389848, cycles0=5154331.566772461, run_open=True,
tb_residual_ns=0
```

`session_id=27`は`run_open=true`のまま——実機がまだ同じrunの中で継続して
PPSロックしていることと整合する。ingest側の`open_run_if_needed`が
「既に開いているrunがあれば何もしない」を正しく守っている(2回目以降の
バッチで新規行が増えていない)ことも、この1件だけしか無い事実から確認できる。

## 次に何が可能になったか

TE絶対値表示は設計・実装・apply・実クラウド確認まで完了した。断線(power_fail)
やセッション再起動でrunが作り直される様子は、まだ実機でその事象が起きていない
ので未確認——次にAC入力線を実際に抜く異常系確認(`docs/open-questions.md`の
既存の未決項目)をやる時に、ついでにアンカーが作り直されることも確認できる。

欠測区間の可視化(dashboard単独、TEと依存無し)は引き続き次のタスクとして残っている。
