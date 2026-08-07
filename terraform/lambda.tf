# zip は ./build_lambda.sh が terraform/builds/<fn>.zip に生成する。
# apply 前に必ず実行すること。
locals {
  build_dir = "${path.module}/builds"
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${local.name}-ingest"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = "${local.build_dir}/ingest.zip"
  source_code_hash = try(filebase64sha256("${local.build_dir}/ingest.zip"), null)
  timeout          = 15
  memory_size      = 256

  environment {
    variables = local.ingest_env
  }
}

resource "aws_lambda_function_url" "ingest" {
  function_name      = aws_lambda_function.ingest.function_name
  authorization_type = "NONE" # 認証はアプリ層のHMACで行う（Namazuと同じ）
}

# --- api（ダッシュボード向けの読み取り専用API）---
resource "aws_lambda_function" "api" {
  function_name    = "${local.name}-api"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = "${local.build_dir}/api.zip"
  source_code_hash = try(filebase64sha256("${local.build_dir}/api.zip"), null)
  timeout          = 15
  memory_size      = 256

  environment {
    variables = local.api_env
  }
}

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE" # ダッシュボードは認証なし（Namazuと同じ）

  cors {
    allow_origins = ["*"]
    allow_methods = ["GET"]
  }
}
