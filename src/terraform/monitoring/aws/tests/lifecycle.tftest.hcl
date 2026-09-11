mock_provider "aws" {}

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

run "explicit_activation" {
  command = plan
  variables { schedule_enabled = true }
  assert {
    condition     = aws_scheduler_schedule.check[0].state == "ENABLED" && aws_scheduler_schedule.check[0].schedule_expression == "cron(17 3 * * ? *)"
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
  variables { runtime_identity = "arn:aws:iam::123456789012:role/drift-scheduler" }
  expect_failures = [terraform_data.guard]
}
