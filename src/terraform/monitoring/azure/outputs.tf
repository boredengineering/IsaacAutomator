output "invocation" { value = var.provision ? local.invocation : [] }
output "report_storage_ownership" {
  value       = "external_retained"
  description = "Customer-owned report storage is not part of monitoring or workstation Terraform state."
}
output "report_storage_ref" { value = var.report_storage_ref }
output "runtime_name" { value = one(azurerm_container_app_job.check[*].name) }
output "scheduler_name" {
  value = var.provision && var.schedule_enabled ? var.name : null
}
output "scheduler_permission" {
  value = "Built-in Container Apps platform schedule; no customer scheduler principal or policy assignment is created."
}
