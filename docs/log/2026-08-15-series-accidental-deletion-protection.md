# `series/`(累積位相データ)の誤削除防止をterraformに追加する

## 何をしたか

`terraform/s3.tf`のdataバケットに、`aws_s3_bucket_versioning`(Enabled)と、
`series/*`への`s3:DeleteObject`/`s3:DeleteObjectVersion`をDenyする
`aws_s3_bucket_policy`を追加した。まだ`terraform apply`はしていない。

## なぜやったか

[PR #50](https://github.com/nna774/Electabuzz/pull/50)でダッシュボード
デプロイの`aws s3 sync --delete`がOTA配布物を巻き込んで消す事故があった
(→ [2026-08-15-dashboard-deploy-delete-incident.md](2026-08-15-dashboard-deploy-delete-incident.md))。
そのPRの対処はドキュメントへの警告追記のみで、技術的なガードレールでは
なかった。

これを受けてユーザーから、NamazuHaUrokoGaNaiの`events/`誤削除防止
([PR #85](https://github.com/nna774/NamazuHaUrokoGaNai/pull/85)——
`deletion_protection_enabled`・PITR・バケットポリシーのDeny・バージョニング)
相当の技術的保護をElectabuzz側にも入れたいという依頼があった。

最初はOTA配布物(`ota/`、dashboardバケット)を対象に着手したが、ユーザーから
「ダッシュボードは消えてもまあいい。波形データ(`series/`)の方を頼む」と
指示があり、対象をdataバケットの`series/`(累積位相、再生成不可の唯一の
原本)に切り替えた。

## 何が分かったか

- Electabuzzの`series/`はNamazuの`events/`と同じ「再生成不可・永久保存」の
  性質を持つが、DynamoDBには載っていない(S3のみ)。DynamoDB側の
  `deletion_protection_enabled`/PITRに相当する保護対象は無い
- dataバケットには`bad/`(CRC不一致の隔離、こちらも永久・証拠なので
  本来は捨てられると困る)もあるが、今回のスコープは`series/`のみとした。
  `bad/`を含めるかは別途判断が要る
- Namazu側で問題になった「S3 Lifecycle expirationはバケットポリシーの
  Denyを迂回する」穴は、dataバケットにまだlifecycle ruleが無いため
  現状は該当しない(→ [docs/storage.md](../storage.md))。将来`raw/`の
  expireを導入する際に確認が必要
- `terraform validate`は`-backend=false`でのinit後に成功を確認した。
  実際のAWSに対する`plan`/`apply`はまだ実施していない

## 何が覆ったか

覆っていない。

## 次に何が可能になったか

`terraform apply`を実施すればdataバケットの`series/`が誤削除から守られる。
適用後は`aws s3api get-bucket-versioning`・バケットポリシーの実値確認が要る
(NamazuのPR #85と同じ確認手順)。`bad/`の扱いは別途検討が必要。
