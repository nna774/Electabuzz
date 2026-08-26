# 2026-08-27 `/recent`並行化(PR #82・#83)をデプロイし、接続プール不足を追加で直した

## 経緯

`/recent`並行化(バックエンドPR #82・フロントエンドPR #83)をマージし、デプロイした。

## デプロイ

- `terraform/build_lambda.sh`でingest/api/watchdog/detectの4本を再ビルド、
  `terraform apply`(0 add/4 change/0 destroy、コードハッシュのみ)。
- dashboard: `aws s3 sync . s3://electabuzz-dashboard-.../ --exclude config.example.js
  --exclude README.md`(`--delete`は付けない。→ dashboard/README.mdの警告、
  過去にOTA配信物ごと消した事故がある)、CloudFront invalidation(`/*`)。
  `curl https://electabuzz.dark-kuins.net/app.js`で新コード(`Promise.all`)が
  実際に配信されていることを確認した。

## デプロイ直後に見つけた追加の不具合

CloudWatch Logsを確認したところ、`/recent`(minutes=30)で
`Connection pool is full, discarding connection`が大量に出ていた。
`store_gridfreq.load_batches_in_range`が`_GET_CONCURRENCY`(16)スレッドで
並行`get_object`するのに対し、boto3 S3クライアントの既定`max_pool_connections`
(10)が足りず、都度TCP/TLSを張り直していた——並行化の効果が接続の張り直し
コストで一部相殺されていた。`lambda/api/handler.py`の`_s3()`で
`max_pool_connections`を並行度に合わせて広げる修正を追加(PR #84)、
再ビルド・再applyして解消(警告ログが消えたことを確認)。

## 実測

直接Lambda URL(CloudFront cacheを経由しない)への`curl`で計測:

| `minutes` | 応答時間(暖機後) |
|---|---|
| 5 | 約1.0〜2.0秒 |
| 30(上限) | 約4.6〜6.4秒 |

接続プール修正後も`minutes=30`は依然4.6秒台——**S3逐次GETの並行化自体は
効いている(壊れた接続の再張りは無くなった)が、api Lambdaの`memory_size`が
256MB(=CPU割当がごく小さい)のため、16並行スレッドのTLS処理がCPUで
律速されている可能性が高い**と推測している。これ以上の改善(Lambdaの
メモリを上げてCPU割当を増やす等)は追加のコスト判断が要るため、
今回はここまでとし、次のタスクとして残す。

## 次に可能なこと

api Lambdaの`memory_size`を上げてCPU律速かどうか実測で切り分ける
(コスト増を伴う判断なのでユーザー確認の上で)。
