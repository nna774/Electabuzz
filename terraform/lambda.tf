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

# --- watchdog（欠測監視: 定期起動して生存台帳の異常を見る。→ docs/cloud.md）---
resource "aws_lambda_function" "watchdog" {
  function_name    = "${local.name}-watchdog"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = "${local.build_dir}/watchdog.zip"
  source_code_hash = try(filebase64sha256("${local.build_dir}/watchdog.zip"), null)
  timeout          = 30
  memory_size      = 256

  environment {
    variables = local.watchdog_env
  }
}

resource "aws_cloudwatch_event_rule" "watchdog" {
  name                = "${local.name}-watchdog"
  description         = "欠測監視watchdogを定期起動する"
  schedule_expression = var.watchdog_schedule
}

resource "aws_cloudwatch_event_target" "watchdog" {
  rule = aws_cloudwatch_event_rule.watchdog.name
  arn  = aws_lambda_function.watchdog.arn
}

resource "aws_lambda_permission" "watchdog_from_events" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.watchdog.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.watchdog.arn
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

# --- detect（series/への新規バッチ到着ごとに周波数逸脱・RoCoF・電圧異常を確定判定。
# → docs/cloud.md「detect」）---
resource "aws_lambda_function" "detect" {
  function_name    = "${local.name}-detect"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = "${local.build_dir}/detect.zip"
  source_code_hash = try(filebase64sha256("${local.build_dir}/detect.zip"), null)
  timeout          = 30
  memory_size      = 256

  environment {
    variables = local.detect_env
  }
}

resource "aws_lambda_permission" "detect_from_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.detect.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.data.arn
}
