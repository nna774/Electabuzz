# detectのprev_batch_key実装・apply、および環境変数の抜け漏れ障害

前段の調査・設計決定は
[log/2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md](2026-08-23-detect-listobjectsv2-cost-and-prev-batch-key-design.md)。
このログは実装・レビュー対応・apply・**apply後に実際に踏んだ障害**の記録。

## 実装

- **batch-uplink**: `devices.record_batch()`に`track_prev_key: bool = False`を
  追加([nna774/batch-uplink#25](https://github.com/nna774/batch-uplink/pull/25)、マージ済み)。
  `True`の時、無条件`UpdateItem`のSET節に
  `prev_batch_key = if_not_exists(last_batch_key, :empty)`を足し、DynamoDBの
  `UpdateExpression`が持つ「SET節の右辺は全て更新前の値を参照する」性質で
  追加リクエスト無しに「上書き前のlast_batch_key」をアトミックに退避する。
  新タグ`v3.1.0`を切ってpush。Namazu側は`v3.0.0`のまま(デフォルトFalseで
  挙動不変、追従不要と合意済み)
- **Electabuzz**:
  - `firmware/platformio.ini`・`firmware/lib/GridFreq/test/run.sh`・
    `terraform/build_lambda.sh`のpinを`v2.12.0`→`v3.1.0`へ。`docs/batch-uplink.md`
    も更新(pinは各プロジェクトが独立に決めるものであり、相手のpin状況を
    気にする対象ではない、という位置づけに書き直した——当初「初めて分岐した」
    という一回性の出来事のように書いていたが、ユーザー指摘で修正)
  - `lambda/ingest/handler.py`の`_record_liveness`が
    `record_batch(..., track_prev_key=True)`を渡すように
  - `lambda/detect/handler.py`の`_prev_boundary_sample_batch`を、
    `store_gridfreq.list_series_keys_in_range`(`ListObjectsV2`)ベースの探索から
    `devices.get_device(device_id)["prev_batch_key"]`を`GetItem`で読むだけの
    方式に書き換え
  - テスト追加・更新(`lambda/tests/test_detect_handler.py`・`test_ingest.py`)

## レビュー指摘と修正

PRへのレビューコメントで、安全策の欠陥を指摘された。

**指摘**: 実装時点の安全策は「取得した直前バッチの`batch_start_us`が現在の
バッチより前であること」だけを見ていた。しかし実際に起きるレース
(`ingest`のS3 PUT→detect起動が、同じ`ingest`呼び出し内で後に実行される
`devices.record_batch`の書き込みより先に走ってしまうケース)で返るのは
「1つ古い(N-1ではなくN-2の)キー」であり、N-2も現在のバッチより過去には
変わりないので、この判定では素通りしてしまう。周波数計算は
`grid_detect.samples_from_batches`側の`dt_actual`レンジチェック(0.5〜2倍の
nominal_dt)で守られ実害は無いが、**電圧異常判定(`voltage_dev_hold_records`の
連続run検出)にはこの時間差ガードが無い**ため、約1バッチ分(実測30秒)の欠測を
挟んだ連続runとして誤って繋がり、電圧異常を誤検知しうる欠陥だった。

**修正**: 「直前バッチ末尾から現在バッチ先頭までの間隔が1レコード分として
妥当な範囲(0.5〜2倍のnominal_dt)か」で判定するよう変更。
`samples_from_batches`が周波数側で使っているのと同じレンジをフェッチの
時点で適用することで、電圧異常側にも同じガードが効くようにした。テストも
実際のレースパターン(N-2の古いキー、gapが大きすぎるケース)に差し替え、
未来/同時刻を指す異常系は別テストとして分離。148件全パス。

## apply、および環境変数の抜け漏れ障害

`terraform plan`は0 add/4 change(zipハッシュのみ)/0 destroyで、IAM変更は
不要と判断していた——detect Lambdaは既に共有ロール(`aws_iam_role.lambda`)で
生存台帳(`aws_dynamodb_table.devices`)への`GetItem`権限を持っていたため。
この判断自体は正しかったが、**別の見落としがあった**。

`terraform apply`実行直後、CloudWatch Logsで`electabuzz-detect`が実機の
バッチ到着のたびに`KeyError('NAMZ_DEVICES_TABLE')`を出して`_process`が
丸ごと例外終了していることに気づいた(11:01:59頃から)。原因は
`terraform/main.tf`の`local.detect_env`に`NAMZ_DEVICES_TABLE`を足し
忘れていたこと——`devices.get_device()`が呼ぶ`_table()`は
`os.environ["NAMZ_DEVICES_TABLE"]`を直接参照するため、環境変数が無いと
即座に例外になる。IAM権限は既にあったため「権限の見落とし」は無いと
安心してしまい、環境変数の見落としに気づくのが遅れた。

**この間(11:01:59〜11:03:57ごろ、約2分)、detectは周波数逸脱・RoCoF・
電圧異常の判定を一切行っていなかった**(例外は`handler()`の外側try/exceptで
捕捉されログに残るだけで、Lambda自体はエラー扱いにならず気づきにくい
壊れ方だった)。

`detect_env`に`NAMZ_DEVICES_TABLE = aws_dynamodb_table.devices.name`を追加し
(IAM変更は無し、0 add/1 change)、`terraform apply`で即座に反映。
新しいコンテナでのバッチ処理(11:03:58の再init以降)がエラー無く完走することを
CloudWatch Logsで確認した。コードと実際のインフラ状態を一致させるための
事後コミットとして[PR #80](https://github.com/nna774/Electabuzz/pull/80)を作成。

## 次に可能になったこと

- 修正後、実際にListBucketコストが減ったことをCost Explorer等で確認
  (安定運転を数日見てから)
- **教訓**: Lambdaの環境変数を新規に必要とするコード変更をする時は、
  IAM権限の確認だけでなく`terraform plan`の差分に対象Lambdaの
  `environment.variables`が実際に含まれているかも必ず見る
  (今回はIAMが既にあったことで「大丈夫」と早合点した)
