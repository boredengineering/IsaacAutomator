output "invocation" {
  value = var.provision ? local.invocation : []
}
output "report_storage_ownership" {
  value       = "external_retained"
  description = "Reports are customer-owned outside monitoring/workload state; neither teardown deletes them."
}
output "report_storage_ref" { value = var.report_storage_ref }
output "runtime_name" { value = one(aws_codebuild_project.check[*].name) }
output "scheduler_name" { value = one(aws_scheduler_schedule.check[*].name) }
output "scheduler_permission" {
  value       = var.provision ? { action = "codebuild:StartBuild", resource = aws_codebuild_project.check[0].arn } : null
  description = "Existing scheduler role must permit only this project; stack does not grant IAM."
}
