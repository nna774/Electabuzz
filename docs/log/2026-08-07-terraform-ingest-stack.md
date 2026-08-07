# terraform/ を新規に立て、ingest分を書く

## やったこと

`docs/roadmap.md`フェーズ7の一部として`terraform/`を新規に作り、**ingestが
動くのに必要な最小構成**を書いた。Namazu の `terraform/` を参照しつつ、
Electabuzz は独立 state・独立バケットに閉じた。

- `versions.tf`: state は Namazu と**同じ保存先バケット**(`nana-terraform-state`)
  だが**keyを`electabuzz.tfstate`に分けて独立**させた。「独立state」は
  保存先バケットが別という意味ではなく、state ファイルが別で
  片方のapplyがもう片方のstateに触らないという意味だと判断した
  (Namazu自身も同じバケット・別keyの構成)
- `s3.tf`: データバケット(`electabuzz-data-<account>`)。**ライフサイクルルールは
  付けていない**——Namazuの`raw/`(90日でexpire)に相当する一時置き場が無く、
  GFRQのバッチは`series/`に置いた時点で最終形だから(→docs/cloud.md)。
  将来必要になったら足す
- `iam.tf`: Lambda実行ロール + ログ権限 + `s3:PutObject`(バケット丸ごと)。
  `series/`と`bad/`を prefix で分けて権限を絞ることはしなかった——
  書き先を間違えるのは`s3keys.py`のバグであって、IAMで防げる種類の
  間違いではないと判断した
- `lambda.tf`: `ingest`関数とFunction URL(認証はアプリ層のHMACに委ねる。
  Namazuと同じ)のみ。**detect/rollup/api/watchdog/CloudFrontは書いていない**
  ——対応するLambda本体がコード上まだ存在しない(`docs/roadmap.md`フェーズ8/9)。
  先にterraformだけ書くと、実装が無いリソース定義を死んだまま残すことになる
- `build_lambda.sh`: `handler.py` + `s3keys.py` + `wire_gridfreq.py`を
  フラットに集め、`batch_uplink`(v1.6.0。firmwareのpinと揃えた)を
  `--no-deps`で同梱する。numpyは同梱していない——ingestはstdlibのみで
  完結する(→docs/wire-format.md、docs/cloud.md)
- `.gitignore`にterraform関連のパターンが足りなかった(`build/`はあったが
  `terraform/builds/`に一致しない、`.terraform.lock.hcl`が無指定)ので、
  Namazu側の慣習に合わせて追加した

## 確認したこと

- `terraform fmt` / `terraform validate`(`-backend=false`でinit。AWSには
  一切触っていない)が緑
- `PYTHON=.venv/bin/python terraform/build_lambda.sh`が緑。`ingest.zip`の
  中身を展開して`handler.py`・`s3keys.py`・`wire_gridfreq.py`・
  `batch_uplink/`が期待通り入っていることを確認した。
  **`batch_uplink`のdist-infoは`1.0.0`のまま**だったが、これはPython側の
  `pyproject.toml`のversionフィールドがC++側のタグ(v1.1.0〜v1.6.0)と
  独立して更新されていないだけで、`pip install`自体は指定した
  `v1.6.0`のgitタグから正しく取得できている(C++側`Uploader`の追加機能は
  Python側のコードに影響しないので、versionが動いていないこと自体は
  自然——バグではない)

## まだやっていないこと

**`terraform apply`は実行していない。** 実際にAWSリソースを作るのは
費用が生じる操作であり、ユーザーの明示的な許可が要る。以下はapply前に
埋める必要がある:

- `terraform.tfvars`(gitignore対象。`terraform.tfvars.example`をコピー)に
  `hmac_secret`を埋める。**`firmware/src/secrets.h`の`kHmacSecret`と
  一致させること**
- `apply`後、出力される`ingest_url`を`firmware/src/secrets.h`の
  `kIngestUrl`へ転記する

## 次に何が可能になったか

`terraform apply`すれば、`env:record`ビルドが実際にAWSまでバッチを送れる
状態になる。フェーズ2(PPS)を待たずに始めた記録・送信(→
[log/2026-08-07-goertzel-cpp-port.md](2026-08-07-goertzel-cpp-port.md))の
最後のピース——「バッチを送る処理」「クラウド側の受け皿」——がこれで揃う。
