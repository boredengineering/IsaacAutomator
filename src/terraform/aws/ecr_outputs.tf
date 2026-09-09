output "ecr_repository_arn" {
  description = "Existing repository authorized for pulls; never owned by this workstation stack."
  value       = var.enable_ecr ? "arn:aws:ecr:${var.ecr_region}:${var.ecr_account_id}:repository/${var.ecr_repository}" : null
  precondition {
    condition     = !var.enable_ecr || (var.ecr_account_id != "" && var.ecr_region != "" && var.ecr_repository != "")
    error_message = "Enabled ECR requires ecr_account_id, ecr_region and ecr_repository even when the workstation is disabled."
  }
}

output "ecr_reader_role_arn" {
  description = "Reader principal for an owner-managed cross-account repository policy."
  value       = var.isaac_workstation_enabled ? module.isaac_workstation[0].ecr_reader_role_arn : null
}
