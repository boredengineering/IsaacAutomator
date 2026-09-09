mock_provider "aws" {}
variables {
  account_id = "123456789012"
  region     = "us-west-2"
  repository = "team/workloads"
}
run "durable_defaults" {
  command = plan
  assert {
    condition     = aws_ecr_repository.images.name == "team/workloads" && !aws_ecr_repository.images.force_delete && aws_ecr_repository.images.image_tag_mutability == "IMMUTABLE" && aws_ecr_repository.images.image_scanning_configuration[0].scan_on_push
    error_message = "Repository must retain images, immutable tags, and push scanning."
  }
  assert {
    condition     = aws_ecr_repository.images.encryption_configuration[0].encryption_type == "AES256" && length(aws_ecr_repository_policy.access) == 0
    error_message = "Default encryption is AES256 with no implicit principal grants."
  }
  assert {
    condition     = output.repository_arn == "arn:aws:ecr:us-west-2:123456789012:repository/team/workloads" && output.repository_url == "123456789012.dkr.ecr.us-west-2.amazonaws.com/team/workloads"
    error_message = "Registry outputs must identify the exact account, region and repository."
  }
}
run "explicit_publisher_and_reader" {
  command = plan
  variables {
    publisher_principal_arns = ["arn:aws:iam::123456789012:role/image-publisher"]
    reader_principal_arns    = ["arn:aws:iam::210987654321:role/workstation-reader"]
  }
  assert {
    condition     = aws_ecr_repository_policy.access[0].repository == aws_ecr_repository.images.name && length(jsondecode(aws_ecr_repository_policy.access[0].policy).Statement) == 2
    error_message = "Only the named repository receives publisher/reader grants."
  }
  assert {
    condition     = jsondecode(aws_ecr_repository_policy.access[0].policy).Statement[0].Resource == "arn:aws:ecr:us-west-2:123456789012:repository/team/workloads" && toset(jsondecode(aws_ecr_repository_policy.access[0].policy).Statement[0].Principal.AWS) == toset(["arn:aws:iam::123456789012:role/image-publisher"]) && toset(jsondecode(aws_ecr_repository_policy.access[0].policy).Statement[0].Action) == toset(["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"])
    error_message = "Only explicit publishers get exact-repository push/pull, never IAM, lifecycle or deletion rights."
  }
  assert {
    condition     = jsondecode(aws_ecr_repository_policy.access[0].policy).Statement[1].Resource == "arn:aws:ecr:us-west-2:123456789012:repository/team/workloads" && toset(jsondecode(aws_ecr_repository_policy.access[0].policy).Statement[1].Principal.AWS) == toset(["arn:aws:iam::210987654321:role/workstation-reader"]) && toset(jsondecode(aws_ecr_repository_policy.access[0].policy).Statement[1].Action) == toset(["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"])
    error_message = "Cross-account readers receive exact-repository pull only."
  }
}
run "customer_managed_encryption" {
  command = plan
  variables { kms_key_arn = "arn:aws:kms:us-west-2:123456789012:key/00000000-0000-0000-0000-000000000000" }
  assert {
    condition     = aws_ecr_repository.images.encryption_configuration[0].encryption_type == "KMS" && aws_ecr_repository.images.encryption_configuration[0].kms_key == var.kms_key_arn
    error_message = "An explicitly supplied existing KMS key must encrypt the repository."
  }
}
