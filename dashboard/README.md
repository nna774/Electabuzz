# dashboard — 系統周波数の可視化

外部依存なしの単一ページ（vanilla JS + Canvas）。ビルド不要。Namazuの
`dashboard/`と同じ構成([README](https://github.com/nna774/NamazuHaUrokoGaNai/blob/master/dashboard/README.md))。

## 機能

`/recent`だけを叩き、直近n分（1/5/15/30）の瞬時周波数を折れ線で表示する。
ステータス行に最終受信からの経過・偏差[mHz]・`timebase_source`のバッジ、
下の表に実効サンプルレート・時間基準の確度・SoC温度などを出す。

**detect/eventsが無い**（→ docs/roadmap.md フェーズ9）ので、Namazuのような
イベント一覧・デバイス一覧タブは無い。生存台帳も無いので、「最終受信からの
経過秒」がそのままデバイスの生存確認を兼ねる。

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

## ローカル確認

```bash
python3 -m http.server 8080   # http://localhost:8080 （?api=... でAPIを指定）
```
