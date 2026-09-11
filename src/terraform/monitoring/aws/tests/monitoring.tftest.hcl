mock_provider "aws" {}

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
    condition     = length(aws_codebuild_project.check) == 0 && length(aws_scheduler_schedule.check) == 0
    error_message = "Default must provision no runtime or scheduler."
  }
}

run "private_report_only_runtime" {
  command = plan
  variables {
    provision          = true
    image              = "123456789012.dkr.ecr.us-east-1.amazonaws.com/automator@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    config_artifact    = "/opt/automator/check.json"
    automator_workdir  = "/opt/automator"
    runtime_identity   = "arn:aws:iam::123456789012:role/drift-reader"
    scheduler_identity = "arn:aws:iam::123456789012:role/drift-scheduler"
    admin_identity     = "arn:aws:iam::123456789012:role/monitoring-admin"
    report_storage_ref = "external-retained-reports"
    vpc_id             = "vpc-12345678"
    subnet_ids         = ["subnet-12345678"]
    security_group_ids = ["sg-12345678"]
  }
  assert {
    condition     = aws_codebuild_project.check[0].environment[0].privileged_mode == false && aws_codebuild_project.check[0].concurrent_build_limit == 1
    error_message = "Runtime must be unprivileged and concurrency-bounded."
  }
  assert {
    condition     = aws_codebuild_project.check[0].vpc_config[0].vpc_id == "vpc-12345678" && aws_scheduler_schedule.check[0].state == "DISABLED"
    error_message = "Private VPC runtime must not activate a schedule implicitly."
  }
  assert {
    condition     = aws_codebuild_project.check[0].service_role != aws_scheduler_schedule.check[0].target[0].role_arn && aws_scheduler_schedule.check[0].target[0].retry_policy[0].maximum_retry_attempts == 0
    error_message = "Roles must be separated and retries bounded."
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

run "reject_rounded_timeout" {
  command = plan
  variables { timeout_seconds = 301 }
  expect_failures = [var.timeout_seconds]
}

run "reject_unsafe_working_directory" {
  command = plan
  variables { automator_workdir = "/opt/repo;curl" }
  expect_failures = [var.automator_workdir]
}
