mock_provider "aws" {
  mock_data "aws_ec2_instance_type_offerings" {
    defaults = { locations = ["us-west-2a"] }
  }
}
mock_provider "tls" {}
variables {
  deployment_name                 = "offline"
  region                          = "us-west-2"
  ssh_port                        = 22
  isaac_workstation_enabled       = true
  isaac_workstation_instance_type = "g5.xlarge"
  ingress_cidrs                   = ["192.0.2.0/24"]
  ami_id                          = "ami-0123456789abcdef0"
}
run "disabled_default" {
  command = plan
  assert {
    condition     = output.ecr_repository_arn == null && output.ecr_reader_role_arn == null
    error_message = "Absent ECR must not configure a repository or reader."
  }
}
run "enabled_from_image" {
  command = plan
  variables {
    from_image     = true
    enable_ecr     = true
    ecr_account_id = "123456789012"
    ecr_region     = "eu-west-1"
    ecr_repository = "team/workloads"
  }
  assert {
    condition     = output.ecr_repository_arn == "arn:aws:ecr:eu-west-1:123456789012:repository/team/workloads"
    error_message = "Root must accept the profile contract also when launching a baked image."
  }
}
run "disabled_workstation" {
  command = plan
  variables { isaac_workstation_enabled = false }
  assert {
    condition     = length(module.isaac_workstation) == 0 && output.ecr_reader_role_arn == null
    error_message = "No workstation means no reader role."
  }
}
run "enabled_missing_configuration_without_workstation" {
  command = plan
  variables {
    isaac_workstation_enabled = false
    enable_ecr                = true
  }
  expect_failures = [output.ecr_repository_arn]
}
run "malformed_root_account" {
  command = plan
  variables {
    isaac_workstation_enabled = false
    ecr_account_id            = "123"
  }
  expect_failures = [var.ecr_account_id]
}
run "malformed_root_region" {
  command = plan
  variables {
    isaac_workstation_enabled = false
    ecr_region                = "cn-north-1"
  }
  expect_failures = [var.ecr_region]
}
run "malformed_root_repository" {
  command = plan
  variables {
    isaac_workstation_enabled = false
    ecr_repository            = "Team/*"
  }
  expect_failures = [var.ecr_repository]
}
