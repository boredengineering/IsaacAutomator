mock_provider "google" {}

variables {
  provision          = true
  project            = "example-monitoring"
  image              = "us-central1-docker.pkg.dev/example-monitoring/tools/automator@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  config_artifact    = "/opt/automator/check.json"
  runtime_identity   = "drift-reader@example-monitoring.iam.gserviceaccount.com"
  scheduler_identity = "drift-scheduler@example-monitoring.iam.gserviceaccount.com"
  admin_identity     = "monitoring-admin@example-monitoring.iam.gserviceaccount.com"
  report_storage_ref = "external-retained-reports"
  network            = "monitoring-private"
  subnetwork         = "monitoring-private"
}

run "explicit_activation" {
  command = plan
  variables { schedule_enabled = true }
  assert {
    condition     = !google_cloud_scheduler_job.check[0].paused && google_cloud_scheduler_job.check[0].http_target[0].http_method == "POST"
    error_message = "Only an explicit second activation flag may schedule the report-only job."
  }
}
run "missing_report_reference" {
  command = plan
  variables { report_storage_ref = "" }
  expect_failures = [terraform_data.guard]
}
run "missing_pinned_config" {
  command = plan
  variables { config_artifact = "" }
  expect_failures = [terraform_data.guard]
}
run "retired_runtime" {
  command = plan
  variables { provision = false }
  assert {
    condition     = output.runtime_name == null && output.report_storage_ownership == "external_retained"
    error_message = "Retirement leaves no runtime and does not own or delete reports."
  }
}
run "reject_shared_identity" {
  command = plan
  variables { runtime_identity = "drift-scheduler@example-monitoring.iam.gserviceaccount.com" }
  expect_failures = [terraform_data.guard]
}
