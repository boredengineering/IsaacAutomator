output "bucket_name" {
  value = aws_s3_bucket.state.bucket
}
output "controller_policy_json" {
  description = "Resource policy grants for review; KMS and restore rights are separate."
  value       = jsonencode(local.controller_policy)
}
