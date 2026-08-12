# カスタムドメイン: electabuzz.dark-kuins.net(ダッシュボード) / api.electabuzz.dark-kuins.net(API)。
# DNSは外部(Cloudflare, nna774/dark-kuins.net-dns)管理なので、
# ACMのDNS検証レコードと本番CNAMEは向こうのリポジトリで手で足す。ここではAWS側のリソースだけ作る。
# 構成はNamazuのterraform/custom_domain.tfを流用。ただしElectabuzzのapi用CloudFrontは
# api_cache.tf側に既に常設済み(30秒TTLキャッシュ目的)なので、ここでは新規distributionを
# 作らず、dashboard.tf/api_cache.tf双方に dynamic aliases/viewer_certificate を足すだけにする。
#
# apply順序(リポジトリまたぎの鶏卵に注意):
#   1. terraform apply -target=aws_acm_certificate.custom
#   2. 出力 acm_validation_records を nna774/dark-kuins.net-dns の records.yml(acm:) に転記してPR→master適用
#   3. terraform apply   (検証完了→CloudFrontにalias付与まで通る)
#   4. 出力 dashboard_cname_target / api_cname_target を records.yml(cname:) に転記してPR→master適用
#   5. dashboard/config.js を https://api.electabuzz.dark-kuins.net に差し替えて再デプロイ(→dashboard/README.md)

locals {
  # 両方セットされている時だけカスタムドメインを有効化する(片方だけは非対応)。
  custom_domain_enabled = var.dashboard_domain != "" && var.api_domain != ""
  # 検証完了後の証明書ARN。distribution はこれを参照して検証完了まで待つ。
  cert_arn = local.custom_domain_enabled ? aws_acm_certificate_validation.custom[0].certificate_arn : null
}

# CloudFront 用証明書は us-east-1 必須。SAN 1枚で両ドメインをまかなう。
resource "aws_acm_certificate" "custom" {
  count                     = local.custom_domain_enabled ? 1 : 0
  provider                  = aws.us_east_1
  domain_name               = var.dashboard_domain
  subject_alternative_names = [var.api_domain]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# DNS が外部なので検証レコードは TF では作らない。Cloudflare に手で入れた後、
# ACM が ISSUED になるのをここで待つ(validation_record_fqdns は敢えて省略)。
resource "aws_acm_certificate_validation" "custom" {
  count           = local.custom_domain_enabled ? 1 : 0
  provider        = aws.us_east_1
  certificate_arn = aws_acm_certificate.custom[0].arn
}
