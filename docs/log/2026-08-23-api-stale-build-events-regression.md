# dashboardの検知イベントが出ない不具合を追い、本体worktreeのビルド成果物の陳腐化が原因と特定した

## 発端

「ダッシュボードを見ると検知イベントが帰ってこない」という報告を受けて調査した。

## わかったこと: `electabuzz-api` のデプロイ済みコードがdetect実装前のバージョンに巻き戻っていた

`/recent`・`/devices`はCloudFront経由・Function URL直叩きいずれも正常応答するのに、
`/events`だけ`{"error": "not found"}`(404)を返していた。DynamoDB(`electabuzz-events`)を
直接scanすると実際には55件のイベントが記録されており、**detectパイプライン自体は
正常に動いていた**——壊れているのはAPI側だけだと分かった。

デプロイ済みLambdaのzipを`aws lambda get-function`で取得して展開すると、`handler.py`に
`/events`の分岐が無く、`grid_events`・`te_anchors`のimportも無い、**detect実装
([log/2026-08-17-detect-gridfreq-v1.md](2026-08-17-detect-gridfreq-v1.md))より前の
`handler.py`**そのものだった。

## 根本原因: 本体worktreeの`terraform/builds/`がworktree間で共有されず陳腐化していた

`terraform/build_lambda.sh`が作る`terraform/builds/*.zip`はgitignore対象で、
worktreeごとに手元で作る前提になっている(→[2026-08-22-detect-dashboard-url-apply.md](2026-08-22-detect-dashboard-url-apply.md)の`terraform.tfvars`と同種の構造)。
本体worktree(`/Users/nana/codes/Electabuzz`)の`terraform/builds/`は**8/15 23:40の
ビルド(detect実装より前)のまま**放置されており、`watchdog.zip`・`detect.zip`は
存在すらしていなかった(この2つがいつ・どうやって消えたかは特定できず)。

2026-08-22、PR #76マージ後に本体worktreeで`terraform apply`した際
([log/2026-08-22-detect-dashboard-url-apply.md](2026-08-22-detect-dashboard-url-apply.md))、
`terraform.tfvars`の欠落には気づいて対処したが、**この古い`builds/api.zip`にも
気づかず**そのままapplyしてしまい、別worktreeで正しくデプロイされていたはずの
`electabuzz-api`のコードを古いものへ上書きしてしまっていた。実際にはapi・detect・
ingest・watchdogの4本全てが同じ経緯で陳腐化しており、`terraform plan`を取り直すと
4本とも`source_code_hash`に差分が出た。

## 対応

本体worktreeで`./terraform/build_lambda.sh`を再実行し4本のzipを作り直した上、
`terraform apply`(0 add / 4 change / 0 destroy、コード反映のみで破壊的変更なし)を
実行。適用後、Function URL直叩き・CloudFront経由いずれも`/events`が55件のイベントを
正しく返すことを確認した。

## 次に何が可能になったか・再発防止の宿題

**`terraform apply`の前に`build_lambda.sh`を実行したか、worktree間で見比べる
一律の手順が無い。** 今回は結果的に実害(古いコードへの巻き戻し)まで出た。
`terraform plan`の`source_code_hash`差分を「意図した変更か」確認する習慣を
徹底する以外に、`build_lambda.sh`をapply前に必ず実行するラッパー(例えば
`terraform apply`を直接叩かずbuild→plan→applyを1コマンドにまとめる)を用意する
選択肢がある。今回のスコープ外としたので[docs/open-questions.md](../open-questions.md)へ送る。
