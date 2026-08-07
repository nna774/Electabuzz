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
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${local.name}-lambda"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}
