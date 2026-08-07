output "ingest_url" {
  description = "firmware secrets.h の kIngestUrl。"
  value       = aws_lambda_function_url.ingest.function_url
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}
