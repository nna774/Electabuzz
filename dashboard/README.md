# dashboard — 系統周波数の可視化

外部依存なしの単一ページ（vanilla JS + Canvas）。ビルド不要。Namazuの
`dashboard/`と同じ構成([README](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/dashboard/README.md))。

## 機能

`/recent`だけを叩き、直近n分（1/5/15/30）の瞬時周波数と**トランス二次側電圧
(`v_rms_mv`)**をそれぞれ折れ線で表示する（2枚のグラフ）。電圧側は`v_rms_mv=0`
(未対応ファーム時代のレコード)を欠測扱いにし、線をつながない。
ステータス行に最終受信からの経過・偏差[mHz]・`timebase_source`のバッジ、
下の表に実効サンプルレート・時間基準の確度・SoC温度・トランス二次側電圧の
最新値などを出す。生存台帳(`/devices`、→ docs/ota.md)が取れれば、
同じ表にビルド版数・受信(壁時計)ベースの生存秒数・累積受信バッチ数・
OTA配信待ちも重ねて出す(取得失敗時やまだ生存台帳を立てていない環境では
単に省く)。

品質テーブルには「トランス二次側電圧」(`v_rms_mv`の実測値そのもの)と
「壁側電圧(概算)」(トランス巻数比・暫定値10.08倍を掛けた参考値)を常時
両方出す。巻数比自体が暫定値かつAFE換算(`v_rms_mv`)も1点校正のみのため、
精密な値のように見せないよう整数V止まりで出す(→ docs/hardware.md
「v_rms_mvの基準点とトランス巻数比」節)。

**電圧グラフの縦軸はチェックボックスで切り替える**(既定は「トランス
二次側電圧」)。チェックを入れると同じ`v_rms_mv`を巻数比倍しただけの
「壁側電圧(概算)」スケールに描き直す(再フェッチはしない)。どちらの
スケールかはグラフ右上のラベルとキャプションで明示する。

画面下に`/events`(detectが確定したイベント、→ docs/cloud.md「detect」)の一覧を出す。
Namazuのようなライブ/イベント/デバイスのタブ構成は取っていない——1ページの情報量が
まだ少なく、イベント自体も稀なため(→ [log/2026-08-17-dashboard-events-section.md](log/2026-08-17-dashboard-events-section.md))。
「受信(壁時計)」の秒数はNamazuの`batch_uplink.devices`と同じ`last_ingest_at_us`基準
——ステータス行の「最終受信」(測定時刻`latest.t_us`基準)とは別系統で、バックフィル中の
見分けに使う。

## 過去の時刻を指定して見る

既定はライブ(直近N分)表示だが、**`開始時刻`欄に日時を指定するとその時刻までの過去の
固定窓を表示する**(`/recent`の`start`パラメータ、→ docs/cloud.md「api」)。「ライブに
戻る」ボタンで解除する。

**検知イベント一覧の行をクリックすると、そのイベントが収まる表示範囲・開始時刻へ
自動でジャンプする**——`#minutes`のプリセット(1/5/15/30分)のうち、イベントの継続時間+
前後の余白が収まる最小のものを選ぶ。

表示状態(表示範囲・自動更新・開始時刻)は`location.hash`(`#live?m=<分>&auto=<0|1>&s=<epoch秒>`)
に反映される。Namazu(nna774/NamazuHaUrokoGaNai)の`dashboard/app.js`と同じ「URLが唯一の
真実」という作りで、リロードやURLの共有で表示状態が復元される。

## API URL の指定

優先度: `?api=<url>` クエリ > 画面の入力欄(localStorage) > `config.js` の
`window.ELBZ_API_URL`。

## デプロイ

```bash
cp config.example.js config.js   # terraform output の api_url を記入
BUCKET=$(cd ../terraform && terraform output -raw dashboard_bucket)
aws s3 sync . "s3://$BUCKET/" --exclude 'config.example.js' --exclude 'README.md'
DIST_ID=$(cd ../terraform && terraform output -raw dashboard_distribution_id)
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths '/*'
```

`terraform output dashboard_url` の CloudFront URL で開く。**S3オブジェクトに
`--cache-control` は付けない**（意図的。ビューワー向けの`Cache-Control: no-cache`は
CloudFront側の`aws_cloudfront_response_headers_policy`が付与する。詳細は
Namazuの`terraform/dashboard.tf`のコメントを参照——同じ構成を踏襲した）。

**上のコマンドに`--delete`を足すな。** このバケットはOTA配信物
(`ota/record/<version>.bin`・`.sha256`、→ [../docs/ota.md](../docs/ota.md)
6章)と相乗りしている。`aws s3 sync . "s3://$BUCKET/" --delete`はローカルの
`dashboard/`に存在しない`ota/`以下を丸ごと削除対象と見なし、配信中の
ファーム一式を消す。実際に2026-08-15、ダッシュボードデプロイ作業中に
誤って`--delete`を付けて実行し、`ota/record/`配下を全滅させる事故が
起きた（幸い当時使い捨てて良い旧ビルドのみだったため実害なし）。

## ローカル確認

```bash
python3 -m http.server 8080   # http://localhost:8080 （?api=... でAPIを指定）
```
