# tools/

実機・クラウドの運用や解析に使うスクリプト置き場。

## S3の`series/`を取ってくる時のキャッシュ

**S3の`series/`から生バッチを取ってくるスクリプトを書く時は、リポジトリ直下の
`.s3cache/`（gitignore対象）にキャッシュを置け。** 一回きりのつもりの取得でも
例外にしない——「今回は使い捨て」のつもりで書いたスクリプトほど、後から
閾値や集計窓を変えて何度も掘り返すことになる。S3取得自体は安い（30秒バッチ単位の
`get_object`数千回・数十MBで数円以下）が、同じバッチを何度も取り直すのは無駄で
遅い。[NamazuHaUrokoGaNai](https://github.com/nna774/NamazuHaUrokoGaNai)の
`tools/README.md` と同じ設計。

- **object keyをそのままローカルパスにミラーする**（`.s3cache/series/2026/08/15/03/0001-<startus>.bin`
  のように、`lambda/s3keys.py` の `series_key()` が返すキーをそのまま `.s3cache/`
  の下にぶら下げる）。時刻範囲で丸ごと切った窓単位でキャッシュすると、窓をわずかに
  ずらしただけで丸ごと引き直しになる。バッチ(30秒粒度)単位のキーでキャッシュすれば、
  窓が重なっている限り差分だけ取得すれば済む。
- `list_objects_v2`（`series_hour_prefixes()` で時別prefixを列挙して回す）は毎回
  本物のS3へ通す。新着バッチを見逃さないためで、コストもほぼ無い。
- `get_object` だけラップして「ローカルにあれば読む・無ければ取ってバイト列を
  そのまま保存する」薄いキャッシュクライアントを渡せばよい。
- worktreeで作業していても `.s3cache/` は**メインチェックアウト側の絶対パス**を
  指すようにする（worktreeごとに毎回別ディレクトリだとキャッシュが効かない）。
- 使い捨てのスクラッチではなく、後から条件を変えて掘り返すための再利用資産として
  扱う（消さずに残しておいてよい）。
- リージョン解決は `awsenv.ensure_region()` を`boto3`クライアント生成前に呼ぶこと
  （`AWS_REGION`だけ設定していると`NoRegionError`で落ちる）。バケット名は
  `ELBZ_BUCKET` 環境変数（無ければ `terraform output data_bucket` で確認）。

**`series/` は `raw/`（Namazu側、90日expire）と違って永久保存前提**なので、
キャッシュが古くなって困ることは無い（→ [docs/cloud.md](../docs/cloud.md)）。

この規約に沿った実例が `check_pps_soak.py`（`timebase_source`の後退・欠測ギャップ・
予期しない再起動を期間内で機械的に検出する。`/recent` APIの`MAX_RECENT_MINUTES`
上限を超えて数時間〜数日単位で見たいときに使う → [docs/log/2026-08-17-phase2-soak-confirmation.md](../docs/log/2026-08-17-phase2-soak-confirmation.md)）。
