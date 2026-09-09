locals {
  ecr_repository_arn = "arn:aws:ecr:${var.ecr_region}:${var.ecr_account_id}:repository/${var.ecr_repository}"
  # IAM role names have a 64-character limit; a hash avoids truncation collisions.
  ecr_reader_name = "${substr(var.prefix, 0, 38)}-ecr-${substr(sha256(var.prefix), 0, 12)}"
}

resource "aws_iam_role" "ecr_reader" {
  count = var.enable_ecr ? 1 : 0
  name  = local.ecr_reader_name
  lifecycle {
    precondition {
      condition     = var.ecr_account_id != "" && var.ecr_region != "" && var.ecr_repository != ""
      error_message = "Enabled ECR requires ecr_account_id, ecr_region and ecr_repository."
    }
    precondition {
      condition     = var.iam_instance_profile == null
      error_message = "Enabled ECR attaches its dedicated reader role; an existing instance profile cannot also be supplied."
    }
    precondition {
      condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region)) && !startswith(var.region, "cn-") && !startswith(var.region, "us-gov-")
      error_message = "Enabled ECR requires a workstation in the commercial AWS partition."
    }
  }
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "ecr_reader" {
  count = var.enable_ecr ? 1 : 0
  name  = "ecr-pull"
  role  = aws_iam_role.ecr_reader[0].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*" # ECR does not support repository scoping for this action.
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
        ]
        Resource = local.ecr_repository_arn
      },
    ]
  })
}

resource "aws_iam_instance_profile" "ecr_reader" {
  count = var.enable_ecr ? 1 : 0
  name  = local.ecr_reader_name
  role  = aws_iam_role.ecr_reader[0].name
}
