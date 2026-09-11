terraform {
  required_version = ">= 1.7, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "5.100.0"
    }
  }
}

provider "aws" { region = var.region }

locals {
  invocation = ["./drift", "check", "--config", var.config_artifact]
  identities = [var.runtime_identity, var.scheduler_identity, var.admin_identity]
}

resource "terraform_data" "guard" {
  lifecycle {
    precondition {
      condition     = !var.schedule_enabled || var.provision
      error_message = "Schedule activation requires explicit provision=true."
    }
    precondition {
      condition     = var.max_attempts_per_day >= var.retries + 1
      error_message = "Scheduled-attempt budget must cover initial execution plus retries."
    }
    precondition {
      condition     = !var.provision || (alltrue([for value in concat(local.identities, [var.image, var.config_artifact, var.report_storage_ref, var.vpc_id, var.automator_workdir]) : value != ""]) && length(distinct(local.identities)) == 3 && length(var.subnet_ids) > 0 && length(var.security_group_ids) > 0)
      error_message = "Provisioning requires pinned image, baked config artifact, three distinct existing identities, externally retained reports, and private VPC configuration."
    }
  }
}

resource "aws_codebuild_project" "check" {
  count                  = var.provision ? 1 : 0
  name                   = var.name
  service_role           = var.runtime_identity
  build_timeout          = ceil(var.timeout_seconds / 60)
  queued_timeout         = 5
  concurrent_build_limit = 1
  artifacts { type = "NO_ARTIFACTS" }
  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    type                        = "LINUX_CONTAINER"
    image                       = var.image
    image_pull_credentials_type = "SERVICE_ROLE"
    privileged_mode             = false
  }
  source {
    type      = "NO_SOURCE"
    buildspec = yamlencode({ version = "0.2", phases = { build = { commands = ["cd ${var.automator_workdir} && ${join(" ", local.invocation)}"] } } })
  }
  logs_config {
    cloudwatch_logs { status = "DISABLED" }
    s3_logs { status = "DISABLED" }
  }
  vpc_config {
    vpc_id             = var.vpc_id
    subnets            = var.subnet_ids
    security_group_ids = var.security_group_ids
  }
  depends_on = [terraform_data.guard]
}

resource "aws_scheduler_schedule" "check" {
  count                        = var.provision ? 1 : 0
  name                         = var.name
  state                        = var.schedule_enabled ? "ENABLED" : "DISABLED"
  schedule_expression          = "cron(${split(" ", var.schedule)[0]} ${split(" ", var.schedule)[1]} * * ? *)"
  schedule_expression_timezone = "UTC"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = "arn:aws:scheduler:::aws-sdk:codebuild:startBuild"
    role_arn = var.scheduler_identity
    input    = jsonencode({ ProjectName = aws_codebuild_project.check[0].name })
    retry_policy {
      maximum_event_age_in_seconds = 900
      maximum_retry_attempts       = var.retries
    }
  }
}
