output "ecr_reader_role_arn" {
  description = "Dedicated EC2 reader role; cross-account pulls also need an owner-managed repository policy."
  value       = var.enable_ecr ? aws_iam_role.ecr_reader[0].arn : null
}
