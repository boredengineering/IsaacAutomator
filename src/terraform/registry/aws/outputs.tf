output "repository_arn" {
  description = "Exact repository ARN for scoped identity policies."
  value       = local.repository_arn
}

output "repository_url" {
  description = "Repository URL; workload profiles must append @sha256:<approved digest>."
  value       = local.repository_url
}
