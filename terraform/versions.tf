terraform {
  required_version = ">= 1.10"

  # Namazu と同じ state 保存用バケットを使うが、key で分ける。
  # **独立 state に閉じる**（→ CLAUDE.md の不変条件）。バケットの共有は state の
  # 保存先が同じというだけで、電力側の apply が地震計側の state に触ることはない。
  backend "s3" {
    bucket       = "nana-terraform-state"
    key          = "electabuzz.tfstate"
    region       = "ap-northeast-1"
    use_lockfile = true
    encrypt      = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project = var.project
    }
  }
}

# CloudFront 用証明書(us-east-1 必須)向けのエイリアス。Namazuのterraform/versions.tfと同じ理由。
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = {
      Project = var.project
    }
  }
}
