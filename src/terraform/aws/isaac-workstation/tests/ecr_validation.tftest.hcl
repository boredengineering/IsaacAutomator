mock_provider "aws" {}
variables {
  prefix          = "offline-workstation"
  deployment_name = "offline"
  keypair_id      = "offline-keypair"
  instance_type   = "g5.xlarge"
  region          = "us-west-2"
  ssh_port        = 22
  ingress_cidrs   = ["192.0.2.0/24"]
  ami_id          = "ami-0123456789abcdef0"
  vpc             = { id = "vpc-offline", cidr_block = "10.0.0.0/16" }
  enable_ecr      = true
  ecr_account_id  = "123456789012"
  ecr_region      = "us-west-2"
  ecr_repository  = "team/workloads"
}
run "missing_account" {
  command = plan
  variables { ecr_account_id = "" }
  expect_failures = [aws_iam_role.ecr_reader]
}
run "missing_region" {
  command = plan
  variables { ecr_region = "" }
  expect_failures = [aws_iam_role.ecr_reader]
}
run "missing_repository" {
  command = plan
  variables { ecr_repository = "" }
  expect_failures = [aws_iam_role.ecr_reader]
}
run "invalid_account" {
  command = plan
  variables { ecr_account_id = "12345678901x" }
  expect_failures = [var.ecr_account_id]
}
run "china_region" {
  command = plan
  variables { ecr_region = "cn-north-1" }
  expect_failures = [var.ecr_region]
}
run "gov_region" {
  command = plan
  variables { ecr_region = "us-gov-west-1" }
  expect_failures = [var.ecr_region]
}
run "invalid_region" {
  command = plan
  variables { ecr_region = "us-east-1.amazonaws.com" }
  expect_failures = [var.ecr_region]
}
run "uppercase_repository" {
  command = plan
  variables { ecr_repository = "Team/workloads" }
  expect_failures = [var.ecr_repository]
}
run "wildcard_repository" {
  command = plan
  variables { ecr_repository = "team/*" }
  expect_failures = [var.ecr_repository]
}
run "empty_path_component" {
  command = plan
  variables { ecr_repository = "team//workloads" }
  expect_failures = [var.ecr_repository]
}
run "short_repository" {
  command = plan
  variables { ecr_repository = "a" }
  expect_failures = [var.ecr_repository]
}
run "too_long_repository" {
  command = plan
  variables { ecr_repository = join("", [for i in range(257) : "a"]) }
  expect_failures = [var.ecr_repository]
}
run "existing_profile_conflict" {
  command = plan
  variables { iam_instance_profile = "operator-existing-profile" }
  expect_failures = [aws_iam_role.ecr_reader]
}
run "noncommercial_workstation" {
  command = plan
  variables { region = "us-gov-west-1" }
  expect_failures = [aws_iam_role.ecr_reader]
}
