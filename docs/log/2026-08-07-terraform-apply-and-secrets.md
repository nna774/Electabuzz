# terraform apply して secrets.h を埋める

## やったこと

[log/2026-08-07-terraform-ingest-stack.md](2026-08-07-terraform-ingest-stack.md)
で書いた ingest 分の terraform を `apply` した。`plan`は7 to add / 0 to change /
0 to destroy（新規スタックなので既存リソースへの影響は無い）で、
実際に7リソースとも作成成功。

出力:
- `data_bucket = "electabuzz-data-486414336274"`
- `ingest_url = "https://nxw7berugrlmtxp6aqbyro2fzq0qizjz.lambda-url.ap-northeast-1.on.aws/"`

`firmware/src/secrets.h`(gitignore対象)を埋めた:
- `kWifiSsid`/`kWifiPass`: Namazuの`tools/devices.json`(`.devices[0]`)から転記。
  自宅の同じWiFiを両プロジェクトで使う
- `kDeviceId=1`。**2号機の予定は無いので、per-deviceの鍵(`device_hmac_secrets`)
  は使わず`hmac_secret`1本のフラット構成にした。**
  terraform側も`device_hmac_secrets`は空のまま
- `kHmacSecret`: `openssl rand -hex 32`で新規生成した32バイトの乱数。
  `terraform.tfvars`(同じくgitignore対象)の`hmac_secret`と同じ値で揃えた
- `kIngestUrl`: 上記apply出力をそのまま転記

`pio run -e record`が引き続き緑であることを確認した。

## OTAについて検討し、今はやらないと決めた

apply中にユーザーから「NamazuはOTAのために秘密情報をNVSパーティションへ
切り出していたが、Electabuzzもそうすべきか」と問われた。**今はやらないと
判断した**——NVS化の動機は「OTAでアプリだけ更新したいのに、コンパイル時定数
だと秘密情報ごと焼き直しになる」という具体的な問題で、Electabuzzには
**OTA自体がまだ無い**（ロードマップにも無い）。2号機の予定も無いので
「同じバイナリを複数デバイスに配る」という利点も効かない。今作ると
「存在しない要件への一般化」になる。

ただし**開発中に何度もUSBで挿し直すのが面倒**という声はもっともなので、
OTAへの要望自体はメモとして [open-questions.md](../open-questions.md) の
「急がないがそのうちやりたいこと」に残した。**着手するときはNamazuと
同じ形(NVS化とセット)で作る**が、ハードウェアが別物なので配線・パーティション
設計はElectabuzz側で決め直す必要がある。

## 次に何が可能になったか

`env:record`を実機に焼けば、`ingest`まで実際にバッチが届く状態が揃った。
残る手順は焼いて実地確認するだけ（→ [progress.md](../progress.md)の該当タスク）。

## 注意: worktreeからのコピーが要る

このセッションは worktree(`crispy-snacking-llama`)内で作業しており、
`firmware/src/secrets.h`・`terraform/terraform.tfvars`はどちらも
gitignore対象なのでコミット・PRには乗らない。**ユーザーが本体の作業ツリーへ
手でコピーする必要がある**（worktreeは他セッションと共有されないローカル
ファイルまでは持ち出さないため）。
