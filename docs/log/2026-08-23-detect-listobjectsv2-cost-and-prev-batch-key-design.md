# detectのListObjectsV2コスト調査と、prev_batch_key設計の決定

## 発端

Namazu側のS3コスト分析(AWS Cost Explorer日次CSV、`~/Downloads/costs.csv`)を見たところ、
2026-08-08以降PutObject/ListBucketが恒常的に底上げされていた。Namazu単体の変更では
説明がつかず、同じAWSアカウントで動いているElectabuzzの稼働開始時期と重なると気づいた。

## 実測(2026-08-23時点)

`aws s3 ls s3://electabuzz-data-486414336274/<prefix>/ --recursive --summarize`で確認。

| prefix | オブジェクト数 | 合計サイズ | 備考 |
|---|---|---|---|
| `series/` | 44,583 | 18.9MB | 2026-08-09開始、1件424B |
| `raw/` | 0 | 0 | 未使用 |
| `bad/` | 0 | 0 | CRC不一致の隔離、未発生 |
| `rollup/` | 0 | 0 | 未実装 |

`series/`は容量としては無視できる小ささ。一方オブジェクト数(44,583件÷約14日≈30秒間隔)
は`lambda/ingest/handler.py`が毎バッチ`put_object`を1回呼ぶ設計(`series/`は永久保存で
expireを掛けない)と一致し、**コストの実体は容量ではなくリクエスト回数**だと分かった。

## LIST費用の段差(2026-08-17)の原因

`lambda/detect/handler.py`の`_prev_boundary_sample_batch`が、バッチ境界をまたぐ周波数
計算の連続性のためだけに、直前バッチ1件を`store_gridfreq.list_series_keys_in_range`
(実体は`s3.list_objects_v2`のページング呼び出し)で毎回探しに行っていた。detectはS3
ObjectCreated(`series/`)トリガーなので**バッチ到着のたびに=30秒ごとにListObjectsV2が
1回飛ぶ**。detectを2026-08-17にterraform applyしており、Namazu側コストCSVで同日に
ListBucketが0.030→0.042ドル/日へ底上げされているのと時期が一致した。

## Namazu側への相談

「探しに行かず、命名規則やDBに残した情報から直接引く」というNamazuが過去に踏んだのと
同じクラスの問題として横展開できないか、Namazu側セッションに相談した(相談ファイルは
`/tmp`に置いていたため恒久記録として本文をここに写す)。

### 相談内容(要旨)

- 共有`batch_uplink/devices.py`の`record_batch()`に変更を加えてよいか、Namazu側で
  衝突が無いか確認したい
- 具体案: `record_batch()`は無条件`UpdateItem`ブロック(`last_batch_key`等をSET)と、
  `last_batch_start_us`を条件付き(単調増加ガード)で更新する別ブロックの2回に分かれて
  いる。前者のSET節に`prev_batch_key = last_batch_key`(退避)を1句足せば、新規の
  DynamoDBリクエストを増やさずに「1つ前のバッチのS3キー」をアトミックに残せる
  (DynamoDBの`UpdateExpression`はSET節の右辺が全て更新前の値を参照するため)
- Electabuzz側のdetectはこの`prev_batch_key`を`GetItem`で読むだけになり、
  `ListObjectsV2`を完全に無くせる見込み
- 確認したいこと: (1)Namazu側で`devices.py`に進行中・計画中の変更は無いか、(2)
  Electabuzzのpin(`v2.12.0`)は古く実際の最新タグは`v3.0.0`——`v2.14.0`で
  `record_batch()`が2回のUpdateItemに分割されているが提案は今も成立するか、(3)
  常に書くか(Namazu側が使わない属性が増える)オプトイン引数にするかの設計方針、
  (4)Electabuzz側で実装してPRを出す形でよいか
- 削減額の規模感は月$0.4程度(概算)と正直に書いた。主眼は「探しに行かず直接引く」
  という設計原則の横展開であることも明記した

### Namazu側からの回答(要旨)

`/Users/nana/codes/batch-uplink`のローカルcloneを直接確認した上での回答。

1. **進行中・計画中の変更は無い。衝突なし。進めてよい。**
   (別に`quarantine-malformed-spill`という古いworktreeにも`devices.py`の差分が
   見えたが、2026-08-10に既にマージ済みのPR #21の古いチェックアウトで無関係と判明)
2. **v2.14.0時点の`record_batch()`実装の確認 → 提案は成立する。**
   無条件ブロック(`last_ingest_at_us`・`last_batch_key`・`fw_version`をSET、
   `batches_total`をADD)と条件付きブロック(`last_batch_start_us`の単調増加ガード)の
   2分割は認識通り。提案の「無条件ブロックのSET節に`prev_batch_key = last_batch_key`
   を足す」は技術的に正しい。Namazu側pinの`v3.0.0`は`s3util.py`削除のみで
   `devices.py`はv2.14.0から変更なし
3. **設計方針への意見 → オプトイン引数(`track_prev_key: bool = False`)を推す。**
   理由: `prev_batch_key`はElectabuzz detect固有の要件でNamazu(加速度計)には使い道が
   無い。batch-uplinkのCLAUDE.mdにある「測る対象に依存しない部分だけを残す」という
   設計方針からすると、常時書く実装は「Namazu側が使わない属性が増えるだけ」になり、
   将来devices.pyを読む人への負債になる。オプトインならNamazuは今回何もしなくても
   挙動が変わらない
4. **Electabuzz側で実装・PRを出す形でよい。** タグ運用について、オプトイン引数にする
   前提ならElectabuzzがマージ後に新タグを切って自分のpinを上げるだけで完結し、
   Namazu側は今回追従不要(「上げるなら両方揃える」の通常ルールは、Namazuが実際に
   `track_prev_key`を使いたくなった時に適用すれば足りる)

## 決定

- `batch_uplink/devices.py`の`record_batch()`に`track_prev_key: bool = False`を追加。
  `True`の時、無条件`UpdateItem`のSET節に
  `prev_batch_key = if_not_exists(last_batch_key, :empty)`を足す(初回で
  `last_batch_key`属性が無い場合のフォールバックとして空文字=「直前バッチ無し」を表す。
  `if_not_exists`無しだと属性が存在しない参照でDynamoDBが`ValidationException`を返す
  ため必須)。**batch-uplinkリポジトリの`detect-prev-batch-key`ブランチ(コミット
  `3f8f504`)に実装済み。PR作成・マージ・新タグ切りはこれから**
- Namazu側は変更なし(デフォルトFalseのまま)
- Electabuzz側は`ingest`が`record_batch(..., track_prev_key=True)`を呼び、`detect`は
  `devices.get_device(device_id)["prev_batch_key"]`を`GetItem`で読んで`get_object`
  一発で直前バッチの末尾レコードを取る設計に変える。**この書き換え自体はまだ**

### タイミングの注意点(要フォールバック)

`ingest`は`series/`へのS3 PUT(→detectを起動する側)の**後**に`devices.record_batch`を
呼んでいる(`lambda/ingest/handler.py:141-147`)。S3イベント通知の配送遅延に対し
`record_batch`のDynamoDB書き込みは同一Lambda内で直後に同期実行されるので、通常は
detectが読む時点で書き込みが先に終わっているはずだが、**保証ではない**。detect側は
「取得した直前バッチの`batch_start_us`が現在のバッチより前であること」を確認し、
そうでなければ`None`扱い(直前サンプル無し)にする安全策を入れる——今のList方式で
「直前バッチが見つからない」場合と同じ扱いに落ちるだけで、安全側に倒れる。

## 次に可能になったこと

- batch-uplinkのPR作成・マージ・新タグ切り(ユーザー確認の上で進める)
- Electabuzz側のpin更新、`ingest`の`track_prev_key=True`化、`detect`の
  `_prev_boundary_sample_batch`のGetItem方式への書き換え、テスト更新
- detect LambdaのIAMに`NAMZ_DEVICES_TABLE`への`GetItem`権限が無ければterraformで追加
- 修正後、実際にListBucketコストが減ったことをCost Explorer等で確認
