# No AWS calls: provider data and resources are mocked, every run is plan-only.
mock_provider "aws" {
  mock_data "aws_ec2_instance_type_offerings" {
    defaults = { locations = ["us-west-2a"] }
  }
}
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
}
run "disabled" {
  command = plan
  assert {
    condition     = length(aws_iam_role.ecr_reader) == 0 && length(aws_iam_role_policy.ecr_reader) == 0 && length(aws_iam_instance_profile.ecr_reader) == 0
    error_message = "Disabled ECR must create no IAM resources."
  }
  assert {
    condition     = var.iam_instance_profile == null
    error_message = "Disabled ECR retains the legacy null profile input (optional/computed on EC2)."
  }
}
run "disabled_existing_profile" {
  command = plan
  variables { iam_instance_profile = "operator-existing-profile" }
  assert {
    condition     = aws_instance.instance.iam_instance_profile == "operator-existing-profile"
    error_message = "Disabled ECR must retain a caller's existing profile."
  }
}
run "enabled_cross_account_cross_region" {
  command = plan
  variables {
    enable_ecr     = true
    ecr_account_id = "123456789012"
    ecr_region     = "eu-west-1"
    ecr_repository = "team/workloads"
  }
  assert {
    condition     = aws_instance.instance.iam_instance_profile == aws_iam_instance_profile.ecr_reader[0].name && aws_iam_instance_profile.ecr_reader[0].role == aws_iam_role.ecr_reader[0].name && aws_iam_role_policy.ecr_reader[0].role == aws_iam_role.ecr_reader[0].name
    error_message = "The reader policy must belong to the role actually attached to EC2."
  }
  assert {
    condition     = aws_instance.instance.metadata_options[0].http_tokens == "required" && aws_instance.instance.metadata_options[0].http_endpoint == "enabled"
    error_message = "ECR credentials require IMDSv2 on the actual EC2 instance."
  }
  assert {
    condition     = jsondecode(aws_iam_role.ecr_reader[0].assume_role_policy).Statement[0].Principal.Service == "ec2.amazonaws.com" && jsondecode(aws_iam_role.ecr_reader[0].assume_role_policy).Statement[0].Action == "sts:AssumeRole"
    error_message = "Only EC2 may assume the reader role."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.ecr_reader[0].policy).Statement[0].Resource == "*" && jsondecode(aws_iam_role_policy.ecr_reader[0].policy).Statement[0].Action == "ecr:GetAuthorizationToken"
    error_message = "Only token authorization uses the required wildcard resource."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.ecr_reader[0].policy).Statement[1].Resource == "arn:aws:ecr:eu-west-1:123456789012:repository/team/workloads" && toset(jsondecode(aws_iam_role_policy.ecr_reader[0].policy).Statement[1].Action) == toset(["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]) && length(jsondecode(aws_iam_role_policy.ecr_reader[0].policy).Statement) == 2
    error_message = "Pull permissions must name the exact repository and never allow publication/deletion."
  }
}
