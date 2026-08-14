# ダッシュボードに生存台帳の受信状態・累積受信数を追加

## 何を決めたか

`api`の`/devices`はビルド版数(`fw_version`)・OTA配信待ち(`pending_ota_version`)
だけでなく`staleness_s`(受信壁時計`last_ingest_at_us`基準の経過秒)・
`batches_total`(累積受信バッチ数)も既に返していたが、ダッシュボードの品質
テーブルはそのうちビルド版数とOTAしか表示していなかった。`dashboard/app.js`の
`renderStatus()`に「受信(壁時計)」「累積受信バッチ数」の2行を追加した。

## なぜそう決めたか

「device statusを受けて保存するやつをNamazuみたいに作れるか」という問いへの
調査で、受信・保存の経路(`electabuzz-devices`テーブル・ingestの
`_record_liveness()`・`api`の`_devices()`)は既に実装済みと判明した
(→ [docs/ota.md](../ota.md)、[docs/cloud.md](../cloud.md))。watchdog通知を
作らない判断も`docs/ota.md`に既に明記済みで、追加実装は不要と分かった。

その上でダッシュボード表示だけがAPIの持つ情報に追いついていなかった
——`staleness_s`/`batches_total`はレスポンスに入っているのに画面に出ていな
かった。特に`staleness_s`(受信壁時計)は、既存のステータス行が使っている
`latest.t_us`(測定時刻)ベースの「最終受信」とは別系統で、`batch_uplink.devices`
のdocstringが言う「生存の主信号」そのもの——バックフィル中は測定側だけを
見ると生存判定を誤りうるので、独立して見せる価値がある。

## 何が覆ったか

`dashboard/README.md`の「生存台帳も無いので〜」という記述は2026-08-09の
OTA実装(生存台帳新設)後も直っていなかった古い記述だったので、あわせて
書き直した。

## 次に何が可能になったか

品質テーブルから「受信は続いているか(壁時計)」「累積で何バッチ受け取ったか」
が見えるようになり、watchdogを作らずとも手元でのデバイス死活監視の材料が
一つ増えた。実装はfetchをモックしたローカルページ(`_devtest.html`、コミット
せず削除済み)+Chrome拡張での描画確認のみで、実機・実クラウド(terraform apply
不要、lambda側の変更も無い)への投入確認はまだ——次にダッシュボードを
デプロイするタイミングで`s3 sync`すれば反映される。
