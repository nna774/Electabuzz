# detect(v1)をterraform applyし、実クラウドで動作確認した

[log/2026-08-17-detect-gridfreq-v1.md](2026-08-17-detect-gridfreq-v1.md)の実装に続き、
ユーザーの明示の許可を得て`terraform apply`を実行した。

## 増分コストの事前見積もり

apply前にユーザーへ概算を提示した。デバイス1台・30秒間隔のバッチ前提で、
Lambda実行回数(月約86,400回)・DynamoDBオンデマンド課金(実際に逸脱が確定した
時だけ書き込み)はいずれもAWSの無料枠に収まり実質$0。detectが境界レコード補完の
ためS3への追加GET/LISTを毎バッチ発行する分だけ月0.5ドル前後増える、という
机上の見積もり。実測ではなくCost Explorerでの確認はこれから。

## apply結果

```
Plan: 4 to add, 4 to change, 0 to destroy
```

- 追加: `aws_dynamodb_table.events`・`aws_lambda_function.detect`・
  `aws_lambda_permission.detect_from_s3`・`aws_s3_bucket_notification.series_created`
- 変更: `aws_iam_role_policy.lambda`(Events用statement追加)・
  `aws_lambda_function.api`(zipハッシュ・`NAMZ_EVENTS_TABLE`追加)・
  `aws_lambda_function.ingest`/`watchdog`(zipハッシュのみ——`common/`を丸ごと
  同梱する既存のビルド方式により、使わない`grid_detect.py`/`grid_events.py`も
  巻き込まれて再デプロイされた。実害無し)
- 破壊的変更なし。`apply complete`

## 実機での動作確認

- `GET /events`(CloudFront経由・直接Function URL経由の両方)が`{"events": []}`を
  返すことを確認(NAMZ_EVENTS_TABLE設定済み、生存台帳が空の初期状態として正しい)
- 稼働中の実機device 1が30秒ごとに送るバッチによって`series/`へのS3
  ObjectCreatedが実際に発火し、**detect Lambdaが起動してエラー無く完走することを
  CloudWatch Logsで確認**(Duration 254ms、Billed Duration 740ms、Memory 97MB。
  通常運転中で逸脱は無いため`electabuzz-events`への書き込みは無し)
- `aws dynamodb describe-table`で`electabuzz-events`が`ACTIVE`・`PAY_PER_REQUEST`・
  `ItemCount=0`であることを確認(想定通りの初期状態)

## 結論

detect(v1)は実装・apply・実機での起動確認まで完了した。**残っているのは
実際の逸脱事例が起きた際にSlack通知・`/events`への記録が正しく動くかの確認と、
しきい値の校正**——安定運転中はどちらも検証できないので、今後の実データ待ち。
