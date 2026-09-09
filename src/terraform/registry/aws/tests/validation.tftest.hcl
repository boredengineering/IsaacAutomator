mock_provider "aws" {}
variables {
  account_id = "123456789012"
  region     = "us-west-2"
  repository = "team/workloads"
}
run "bad_account" {
  command = plan
  variables { account_id = "12345678901x" }
  expect_failures = [var.account_id]
}
run "empty_account" {
  command = plan
  variables { account_id = "" }
  expect_failures = [var.account_id]
}
run "china_region" {
  command = plan
  variables { region = "cn-north-1" }
  expect_failures = [var.region]
}
run "gov_region" {
  command = plan
  variables { region = "us-gov-west-1" }
  expect_failures = [var.region]
}
run "empty_region" {
  command = plan
  variables { region = "" }
  expect_failures = [var.region]
}
run "uppercase_repository" {
  command = plan
  variables { repository = "Team/images" }
  expect_failures = [var.repository]
}
run "wildcard_repository" {
  command = plan
  variables { repository = "team/*" }
  expect_failures = [var.repository]
}
run "empty_repository" {
  command = plan
  variables { repository = "" }
  expect_failures = [var.repository]
}
run "long_repository" {
  command = plan
  variables { repository = join("", [for i in range(257) : "a"]) }
  expect_failures = [var.repository]
}
run "wildcard_publisher" {
  command = plan
  variables { publisher_principal_arns = ["*"] }
  expect_failures = [var.publisher_principal_arns]
}
run "root_publisher" {
  command = plan
  variables { publisher_principal_arns = ["arn:aws:iam::123456789012:root"] }
  expect_failures = [var.publisher_principal_arns]
}
run "wildcard_role_publisher" {
  command = plan
  variables { publisher_principal_arns = ["arn:aws:iam::123456789012:role/*"] }
  expect_failures = [var.publisher_principal_arns]
}
run "session_publisher" {
  command = plan
  variables { publisher_principal_arns = ["arn:aws:sts::123456789012:assumed-role/publisher/session"] }
  expect_failures = [var.publisher_principal_arns]
}
run "wildcard_reader" {
  command = plan
  variables { reader_principal_arns = ["*"] }
  expect_failures = [var.reader_principal_arns]
}
run "invalid_kms_arn" {
  command = plan
  variables { kms_key_arn = "alias/images" }
  expect_failures = [var.kms_key_arn]
}
run "wrong_kms_region" {
  command = plan
  variables { kms_key_arn = "arn:aws:kms:eu-west-1:123456789012:key/00000000-0000-0000-0000-000000000000" }
  expect_failures = [aws_ecr_repository.images]
}
run "wrong_kms_account" {
  command = plan
  variables { kms_key_arn = "arn:aws:kms:us-west-2:210987654321:key/00000000-0000-0000-0000-000000000000" }
  expect_failures = [aws_ecr_repository.images]
}
