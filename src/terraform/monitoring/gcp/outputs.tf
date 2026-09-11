output "invocation" { value = var.provision ? local.invocation : [] }
output "report_storage_ownership" {
  value       = "external_retained"
  description = "Customer-owned report storage is not part of monitoring or workstation Terraform state."
}
output "report_storage_ref" { value = var.report_storage_ref }
output "runtime_name" { value = one(google_cloud_run_v2_job.check[*].name) }
output "scheduler_name" { value = one(google_cloud_scheduler_job.check[*].name) }
output "scheduler_permission" {
  value       = var.provision ? { role = "roles/run.invoker", resource = google_cloud_run_v2_job.check[0].id } : null
  description = "Existing scheduler identity needs jobs.run on this job only; no public invoker or IAM grant is created."
}
