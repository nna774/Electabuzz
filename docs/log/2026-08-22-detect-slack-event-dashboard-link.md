# detectのSlack通知「イベント」欄をdashboardグラフへのリンクにする

## きっかけ

detect(`lambda/detect/handler.py`)のSlack通知はイベントID(`0001-freq_deviation-...`)を
そのままテキストで出すだけで、実際にそのイベントの波形を見るには`/events`を自分で
叩くかdashboardのイベント一覧から探す必要があった。2026-08-20に追加した
dashboardのハッシュルーティング(`#live?m=&auto=&s=`、
→[2026-08-20-dashboard-event-time-hash-routing.md](2026-08-20-dashboard-event-time-hash-routing.md))
で「イベント一覧の行クリックでそのイベントが収まる範囲へジャンプする」機能は既にあるので、
Slack通知からも同じ範囲へ直接ジャンプできるようにした。

## 実装

- `lambda/detect/handler.py`に`_event_view_window()`を追加。
  `dashboard/app.js`の`eventViewWindow()`と**同じ式**(継続時間+前後の余白、
  `EVENT_VIEW_MINUTES=(1,5,15,30)`への丸め)をPython側に複製している。
  移植元(JS)を直接呼べないので複製せざるを得ないが、値がズレるとリンク先の
  表示範囲がdashboard上のクリック操作と食い違うため、コメントで対応関係を明記した
- `_event_link()`でイベントIDを`<url|eid>`形式のSlack mrkdwnリンクに変換する。
  `NAMZ_DASHBOARD_URL`未設定ならID文字列のまま返す——watchdogの`_device_field`
  (デバイス番号をダッシュボードリンクにする既存パターン)と同じ考え方
- `auto=0`固定にした。過去の一時点のグラフを見せる用途でauto-refreshは不要
- `batch_uplink.notify`パッケージ側に`event_field()`という同名のヘルパーが既にあるが、
  そちらは`#event/<id>`という**Electabuzzのdashboardには存在しないルート**を指す
  (Namazu由来。Electabuzzのdashboardは`#live?...`ルーティングしか持たない単一ビュー
  構成のため)ので使わなかった。同じ問題はwatchdogの`_device_field`が指す`#device/<id>`
  にも既にある(pathを無視してlive画面が開くだけ)が、今回のスコープ外として触っていない
- terraformの`detect_env`(`terraform/main.tf`)に`NAMZ_DASHBOARD_URL`を追加
  (watchdog_envの式と同一)。**`terraform apply`はまだ**——費用は増えない変更
  (環境変数1個の追加)だが、明示の許可を得てから行う

## 確認

`lambda/tests/test_detect_handler.py`にテストを追加: 通知の「イベント」欄が
`NAMZ_DASHBOARD_URL`設定時にリンクになること・未設定時はID文字列のままフォールバック
すること・`_event_view_window()`が短い/長いイベント両方でdashboard側のプリセットと
一致する値を返すこと。`lambda/tests`全体144件・`terraform validate`とも緑。
Slack上での実際の見た目(リンク先クリックで実際にグラフが開くか)は`terraform apply`後の
実クラウド確認が必要で、まだ行っていない。
