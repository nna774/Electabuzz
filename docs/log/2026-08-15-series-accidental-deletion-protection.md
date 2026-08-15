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

`terraform apply`を実施すればdataバケットの`series/`・`bad/`が誤削除から
守られる。適用後は`aws s3api get-bucket-versioning`・バケットポリシーの
実値確認が要る(NamazuのPR #85と同じ確認手順)。

## 追記: `bad/`も対象に加えた

上記で「別途判断が要る」としていた`bad/`(CRC不一致の隔離)について、
ユーザーから「入れとこう」と指示があり、同じDenyポリシーの対象に加えた。
`bad/`も`series/`と同じく「捨てると証拠が消える」再生成不可のデータ
(→ docs/cloud.md)なので、除外する理由が無いという判断。バケット
ポリシーの`resources`に`${aws_s3_bucket.data.arn}/bad/*`を追加しただけで、
バージョニングは元々バケット全体に効いているため変更不要。

## 追記: noncurrent versionの無期限蓄積を検証セッションの指摘で修正した

別セッション(検証専用)からのクロスセッションメッセージで、`series_key()`/
`bad_key()`が「同一内容の再送は同じキーに上書き」を意図的な冪等設計として
持っている(→`lambda/s3keys.py`)ため、バージョニング有効化だけだと
batch-uplinkの通常のspool/retryのたびにnoncurrent versionが際限なく
積み上がる、という指摘を受けた。Namazu側(PR #85)は同じ状況に対して
`noncurrent_version_expiration`を明示的に足して対処していたのに、
このPRではその部分だけ落ちていた——「Namazu #85と同じ構成」と謳って
いながら実際には片翼だけコピーしていたという抜け。

`lambda/s3keys.py`のdocstringを実際に読んで指摘が正しいと確認した上で、
current versionのexpireとは別物として`noncurrent_version_expiration`
(30日、Namazu #85の値を踏襲した暫定値)だけを持つ`aws_s3_bucket_lifecycle_configuration`
を追加した。current versionの保存方針(永久)は変えていない。

## 何が覆ったか(追記分)

「dataバケットにはlifecycle ruleが無い」という記述は、current version
expireについては引き続き真だが、noncurrent version expireについては
このコミットで覆った(lifecycle ruleを新規追加した)。

## 追記2: docs/storage.mdの「別の話」という切り分けを同一セッションから訂正された

上の追記で書いた「Denyポリシーとは無関係な操作なので、Lifecycle-Deny
迂回の穴とは別の話」という説明に対し、同じ検証セッションから再度指摘が
入った——noncurrent versionの自動削除もLifecycle駆動である以上、
根っこの仕組み(Lifecycle expirationはIAMプリンシパルのリクエストとして
発行されないためバケットポリシー評価の対象外になる、というAWSの既知の
挙動)はNamazu側の穴と全く同じ。今回はcurrent versionを消さないぶん
壊滅度は低いが、「`series/`・`bad/`を誤って上書きした場合、元のバージョンへ
復旧できる猶予はDenyポリシーの有無に関係なくnoncurrent_days(30日)で
頭打ちになる」という形で同じ仕組みが効いている、切り離すのは不正確、
という指摘だった。ユーザー(nana)にも経緯を共有した上で「あってもいいかも」
と伝えてほしいと言われて送られてきたメッセージ。

指摘を認め、[terraform/s3.tf](../terraform/s3.tf)の`cleanup-noncurrent-versions`
ルール直上に、Namazu PR #85のs3.tfコメントと同趣旨の警告(このルールは
Denyポリシーを迂回してnoncurrent versionを自動削除する、復旧猶予は
30日が上限)を追加し、[docs/storage.md](../storage.md)の「別の話」という
表現も「同じ仕組みが別の形で残っている」に書き直した。
