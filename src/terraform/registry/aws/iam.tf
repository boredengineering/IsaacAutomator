locals {
  pull_actions = [
    "ecr:BatchGetImage",
    "ecr:GetDownloadUrlForLayer",
    "ecr:BatchCheckLayerAvailability",
  ]
  publish_actions = concat(local.pull_actions, [
    "ecr:InitiateLayerUpload",
    "ecr:UploadLayerPart",
    "ecr:CompleteLayerUpload",
    "ecr:PutImage",
  ])
}

# This root owns the complete repository policy. Edit principal inputs here,
# not a second aws_ecr_repository_policy or an out-of-band competing policy.
# GetAuthorizationToken belongs in each principal's identity policy, NOT here.
resource "aws_ecr_repository_policy" "access" {
  count      = length(var.publisher_principal_arns) + length(var.reader_principal_arns) > 0 ? 1 : 0
  repository = aws_ecr_repository.images.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      length(var.publisher_principal_arns) == 0 ? [] : [{
        Sid       = "ExplicitPublishers"
        Effect    = "Allow"
        Principal = { AWS = sort(tolist(var.publisher_principal_arns)) }
        Action    = local.publish_actions
        Resource  = local.repository_arn
      }],
      length(var.reader_principal_arns) == 0 ? [] : [{
        Sid       = "ExplicitReaders"
        Effect    = "Allow"
        Principal = { AWS = sort(tolist(var.reader_principal_arns)) }
        Action    = local.pull_actions
        Resource  = local.repository_arn
      }],
    )
  })
}
