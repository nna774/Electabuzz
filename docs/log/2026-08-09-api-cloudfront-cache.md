# `/recent` APIをCloudFront経由にし、30秒TTLでキャッシュした

## 何を決めたか

`lambda/api/handler.py`(`/recent`)の手前にCloudFront distributionを新設し
(`terraform/api_cache.tf`)、30秒固定TTL(`min_ttl=default_ttl=max_ttl=30`)で
キャッシュするようにした。キャッシュキーは`minutes`・`start`のクエリのみ
(Cookie・ヘッダは含めない)。`terraform/outputs.tf`の`api_url`はこの
CloudFrontドメインを指すよう変更し、生のLambda Function URLは
`api_url_direct`として切り分け用に残した。

**まだ`terraform apply`していない。** このworktreeには`terraform.tfvars`が
無い(gitignore対象、本体の作業ツリーにしか無い)ため、`apply`はこの変更が
本体へマージされた後に実行する。

## なぜそう決めたか

きっかけは「ダッシュボードにカスタムドメインを割り当てて他の人にも見せたい」
という話。今の`api`のLambda Function URLは`authorization_type = "NONE"`・
CORS `allow_origins = ["*"]`で、レート制限もWAFも無い(`terraform/lambda.tf`)。
自動更新ONの状態で開きっぱなしにすると10秒に1回`/recent`を叩き、その都度
Lambda内で`ListObjectsV2`+`GetObject`をS3へ発行する(`lambda/store_gridfreq.py`)
——**閲覧人数がそのままS3/Lambdaの呼び出し回数に比例する**構造だった。人数が
今の1〜2人程度から不特定多数に変わる前に、この比例関係そのものを崩しておきたい。

30秒という数値はGFRQのバッチ間隔(`record_rate_mhz`1Hz×30レコード=30秒/本、
→ [wire-format.md](../wire-format.md))から出した。**S3の`series/`に新しい
バッチが増えるのがそもそも30秒に1回**なので、それより短い間隔でオリジンを
叩いても新しいデータは出てこない。30秒キャッシュは「鮮度を捨てる」トレード
オフではなく、「元から存在しない鮮度をポーリングで買いに行くのをやめる」
だけの変更になる。ダッシュボードの鮮度表示(`app.js`の`ageS`)は`latest.t_us`
——実データのタイムスタンプそのもの——を見ているので、キャッシュが返す
レスポンスが多少古くても「古いことが古いまま正直に表示される」原則
(→ [timebase.md](../timebase.md))は崩れない。

これで同時何人が見ていようと、オリジン(Lambda→S3)へのアクセス頻度は
「クエリの組み合わせ数(実質`minutes`の選択肢4つ)× 1回/30秒」にほぼ収束する。
閲覧人数に対して定数になる。

WAFのレート制限(スクリプトによる連打対策)は別の話として見送った——今回の
変更は「正規のブラウザ閲覧が増えること」への対策で、「悪意あるアクセスの
頻度そのもの」への対策ではない。後者は実際にURLを広く晒すフェーズになって
から検討すれば足りると判断し、[open-questions.md](../open-questions.md)に
積み残した。

## 何が覆ったか

覆ってはいない。`api`をFunction URL直結にした当初の設計(→ [cloud.md](../cloud.md))
自体は正しかった——閲覧者が少ない間はCloudFrontを挟む理由が無く、「存在しない
要件への一般化」を避けていただけだ。今回は要件(不特定多数への公開)が実際に
見えてきたので、そのタイミングで足した。

## 次に何が可能になったか

- `terraform apply`後、`dashboard/config.js`の`window.ELBZ_API_URL`を新しい
  `api_url`(CloudFront経由)に向け直してデプロイし直せば、閲覧人数を気にせず
  カスタムドメインを割り当てる作業に進める
- 生のFunction URL(`api_url_direct`)は切り分け用に残っているので、CloudFront
  経由で異常があった場合の原因切り分けに使える
