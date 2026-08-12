# ダッシュボード/APIにカスタムドメインを割り当てる作業を開始した

## 経緯

CloudFrontの既定ドメイン(`d749zv0enwqn1.cloudfront.net`等)は覚えにくく共有しづらい、という指摘から着手。`terraform/dashboard.tf`には元々「必要になったらNamazuのcustom_domain.tfを参照」という伏線コメントがあり、導入自体は以前から想定済みだった。

## やったこと

Namazuの`terraform/custom_domain.tf`の構成をほぼそのまま流用した。差分は、Electabuzzの`api_cache.tf`が(30秒TTLキャッシュ目的で)既にAPI用CloudFront distributionを常設していた点——Namazu側は`custom_domain.tf`内でカスタムドメイン用に新規distributionをcount 0/1で作っていたが、Electabuzzでは既存の`dashboard.tf`/`api_cache.tf`両distributionに`aliases`と`dynamic "viewer_certificate"`を足すだけで済んだ。

- `terraform/versions.tf`: ACM証明書(CloudFront向けはus-east-1必須)用に`aws.us_east_1`のproviderエイリアスを追加
- `terraform/variables.tf`: `dashboard_domain`(既定`electabuzz.dark-kuins.net`)・`api_domain`(既定`api.electabuzz.dark-kuins.net`)を追加
- `terraform/custom_domain.tf`(新規): `aws_acm_certificate.custom`(SAN 1枚で両ドメイン)・`aws_acm_certificate_validation.custom`。DNSが外部(Cloudflare)管理のため検証レコード自体はTerraformで作らず、ISSUEDになるのを待つだけ
- `terraform/dashboard.tf`・`terraform/api_cache.tf`: `aliases`とdynamic `viewer_certificate`(カスタムドメインありならACM、無ければCloudFront既定証明書)を追加
- `terraform/outputs.tf`: `dashboard_url`/`api_url`をカスタムドメイン優先に変更、DNSリポジトリへ転記するための`acm_validation_records`/`dashboard_cname_target`/`api_cname_target`を追加

`terraform plan`で確認(作成2件・in-place更新3件・破壊0件)。`terraform apply -target=aws_acm_certificate.custom`を実行し、ACM証明書(PENDING_VALIDATION)を実際に発行して検証用CNAMEの実値を得た。

DNS(`nna774/dark-kuins.net-dns`)は外部リポジトリ管理なので、取得した検証用CNAMEと(既存distributionの)本番向けCNAMEを`records.yml`に追記し、PR [nna774/dark-kuins.net-dns#1](https://github.com/nna774/dark-kuins.net-dns/pull/1) を作成した。masterへマージ・適用されるのは別セッションの担当。

## 何が覆ったか

なし(新規)。

## 次に何が可能になったか

DNS PRがマージされ、DNS伝播が確認できたら:

1. Electabuzz側で`terraform apply`(残り: ACM検証完了待ち→両CloudFrontへの`alias`付与)
2. `dashboard/config.js`を`https://api.electabuzz.dark-kuins.net`に差し替えて再デプロイ(→[dashboard/README.md](../../dashboard/README.md))
3. `https://electabuzz.dark-kuins.net` / `https://api.electabuzz.dark-kuins.net`の疎通確認

apply順序の詳細は`terraform/custom_domain.tf`冒頭のコメントに残した。
