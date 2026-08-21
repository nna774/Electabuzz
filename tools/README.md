# tools/

実機・クラウドの運用や解析に使うスクリプト置き場。

## S3から読む時は常にs3cache（`tools/s3cache.py`）

**tools/配下でS3の`series/`から読む（`list_objects_v2`/`get_object`）コードは、生の
`boto3.client("s3")`を自作せず常に`tools/s3cache.py`を使うこと。** `series/`は
書き込み後不変なので、1回しか使わないつもりの解析でもキャッシュして損は無い——
「今回は使い捨て」のつもりで書いたスクリプトほど、後から閾値や集計窓を変えて
何度も掘り返すことになる。S3取得自体は安い（30秒バッチ単位の`get_object`数千回・
数十MBで数円以下）が、同じバッチを何度も取り直すのは無駄で遅い。
[NamazuHaUrokoGaNai](https://github.com/nna774/NamazuHaUrokoGaNai)の
`tools/s3cache.py`と同じ設計。

```python
import s3cache
s3 = s3cache.cached_client()  # store_gridfreq.list_series_keys_in_range 等にそのまま渡せる
```

- **書き込み(`put_object`/`copy_object`)には使えない**。`CachedS3`は読み取り2メソッド
  (`list_objects_v2`/`get_object`)しか実装していない。S3へ書くツールを新しく書く時は、
  書き込み用に生の`boto3.client("s3")`をそのまま使うこと（読み取り箇所だけ
  s3cacheに差し替えるのは構わない）。
- **object keyをそのままローカルパスにミラーする**（`.s3cache/series/2026/08/15/03/0001-<startus>.bin`
  のように、`lambda/s3keys.py` の `series_key()` が返すキーをそのまま `.s3cache/`
  の下にぶら下げる）。時刻範囲で丸ごと切った窓単位でキャッシュすると、窓をわずかに
  ずらしただけで丸ごと引き直しになる。バッチ(30秒粒度)単位のキーでキャッシュすれば、
  窓が重なっている限り差分だけ取得すれば済む。
- キャッシュするのは`get_object`だけ（`list_objects_v2`は毎回本物のS3へ通す。新着
  バッチを見逃さないためで、コストもほぼ無い）。
- worktreeで作業していても`.s3cache/`は**メインチェックアウト側の絶対パス**を指す
  （`git rev-parse --git-common-dir`の親を使う。worktreeごとに毎回別ディレクトリだと
  キャッシュが効かない。`tools/s3cache.py`はこれを内部で解決済み）。
- 使い捨てのスクラッチではなく、後から条件を変えて掘り返すための再利用資産として
  扱う（消さずに残しておいてよい）。gitignore対象なのでリポジトリには含まれない。
- リージョン解決は `awsenv.ensure_region()` を`boto3`クライアント生成前に呼ぶこと
  （`AWS_REGION`だけ設定していると`NoRegionError`で落ちる）。バケット名は
  `ELBZ_BUCKET` 環境変数（無ければ `terraform output data_bucket` で確認）。

**`series/` は `raw/`（Namazu側、90日expire）と違って永久保存前提**なので、
キャッシュが古くなって困ることは無い（→ [docs/cloud.md](../docs/cloud.md)）。

利用例が `check_pps_soak.py`（`timebase_source`の後退・欠測ギャップ・予期しない
再起動を期間内で機械的に検出する。`/recent` APIの`MAX_RECENT_MINUTES`上限を超えて
数時間〜数日単位で見たいときに使う → [docs/log/2026-08-17-phase2-soak-confirmation.md](../docs/log/2026-08-17-phase2-soak-confirmation.md)）。
