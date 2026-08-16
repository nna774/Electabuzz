data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ingest/api で1ロールを共有する（Namazuと同じ構成）。ingest が書くのは series/、
# CRC不一致時は bad/。api はダッシュボード向けに series/ を読む・列挙する。
# prefix で権限を分けていない——書き先/読み先を間違えるのは s3keys.py や
# store_gridfreq.py のバグであって、IAM が防げる種類の間違いではない。
data "aws_iam_policy_document" "lambda" {
  statement {
    sid    = "S3Data"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.data.arn,
      "${aws_s3_bucket.data.arn}/*",
    ]
  }

  # デバイス生存台帳(→ devices.tf)。ingestが書く(record_batch・OTA配信対象の
  # 解放)、apiが読む(/devices・OTA配信対象の照会)。prefixで権限を分けない理由は
  # 上のS3Dataと同じ——読み書きを間違えるのはコードのバグであってIAMの仕事ではない。
  statement {
    sid    = "Devices"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.devices.arn]
  }

  # detectイベント台帳(→ events.tf)。detectが書く(grid_events.record)、
  # apiが読む(/events・grid_events.recent_events)。
  statement {
    sid    = "Events"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.events.arn]
  }

  # TE絶対値表示のセッションアンカー(→ te_anchors.tf)。ingestが書く
  # (te_anchors.open_run_if_needed/close_open_run)、apiが読む
  # (_series_payloadのTE計算、te_anchors.anchors_for_session)。
  statement {
    sid    = "TeAnchors"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.te_anchors.arn]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${local.name}-lambda"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}
