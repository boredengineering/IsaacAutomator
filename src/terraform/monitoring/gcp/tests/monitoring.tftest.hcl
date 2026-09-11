mock_provider "google" {}

run "reject_identity_urls" {
  command = plan
  variables {
    runtime_identity   = "https://user:secret@host"
    scheduler_identity = "https://user:secret@host"
    admin_identity     = "https://user:secret@host"
  }
  expect_failures = [var.runtime_identity, var.scheduler_identity, var.admin_identity]
}

run "disabled_by_default" {
  command = plan
  assert {
    condition     = length(google_cloud_run_v2_job.check) == 0 && length(google_cloud_scheduler_job.check) == 0
    error_message = "Default must provision no runtime or scheduler."
  }
}

run "private_report_only_runtime" {
  command = plan
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
  assert {
    condition     = google_cloud_run_v2_job.check[0].template[0].template[0].service_account == var.runtime_identity && google_cloud_scheduler_job.check[0].http_target[0].oauth_token[0].service_account_email == var.scheduler_identity
    error_message = "Scheduler OAuth identity and runtime identity must be distinct and explicit."
  }
  assert {
    condition     = google_cloud_run_v2_job.check[0].template[0].template[0].vpc_access[0].egress == "ALL_TRAFFIC" && google_cloud_scheduler_job.check[0].paused
    error_message = "Private VPC runtime must not activate a schedule implicitly."
  }
  assert {
    condition     = google_cloud_run_v2_job.check[0].template[0].parallelism == 1 && google_cloud_run_v2_job.check[0].template[0].task_count == 1 && google_cloud_run_v2_job.check[0].template[0].template[0].max_retries == 0 && google_cloud_scheduler_job.check[0].retry_config[0].retry_count == 0
    error_message = "Bound concurrency and avoid multiplying scheduler and runtime retries."
  }
  assert {
    condition     = output.invocation == tolist(["./drift", "check", "--config", "/opt/automator/check.json"]) && output.report_storage_ownership == "external_retained"
    error_message = "Report-only invocation and externally retained storage are required."
  }
}

run "reject_implicit_activation" {
  command = plan
  variables { schedule_enabled = true }
  expect_failures = [terraform_data.guard]
}
run "reject_correction" {
  command = plan
  variables { correction = "approval_required" }
  expect_failures = [var.correction]
}
run "reject_unpinned_image" {
  command = plan
  variables { image = "example/automator:latest" }
  expect_failures = [var.image]
}
run "reject_excess_budget" {
  command = plan
  variables { retries = 4 }
  expect_failures = [terraform_data.guard]
}

run "reject_unsupported_registry" {
  command = plan
  variables { image = "registry.example/automator@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  expect_failures = [var.image]
}
