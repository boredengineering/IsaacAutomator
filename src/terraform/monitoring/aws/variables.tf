variable "name" {
  type    = string
  default = "isaac-drift-check"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "image" {
  type    = string
  default = ""
  validation {
    condition     = var.image == "" || can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[A-Za-z0-9._/-]+@sha256:[a-f0-9]{64}$", var.image))
    error_message = "Invalid image; only safe report-only pinned runtime inputs and once-daily UTC schedules are supported."
  }
}

variable "config_artifact" {
  type    = string
  default = ""
  validation {
    condition     = var.config_artifact == "" || can(regex("^/[A-Za-z0-9_/-]+(\\.[A-Za-z0-9_-]+)*$", var.config_artifact))
    error_message = "Invalid config_artifact; only safe report-only pinned runtime inputs and once-daily UTC schedules are supported."
  }
}

variable "runtime_identity" {
  type    = string
  default = ""
  validation {
    condition     = var.runtime_identity == "" || can(regex("^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+$", var.runtime_identity))
    error_message = "Runtime identity must be an existing commercial AWS role ARN."
  }
}

variable "scheduler_identity" {
  type    = string
  default = ""
  validation {
    condition     = var.scheduler_identity == "" || can(regex("^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+$", var.scheduler_identity))
    error_message = "Scheduler identity must be an existing commercial AWS role ARN."
  }
}

variable "admin_identity" {
  type    = string
  default = ""
  validation {
    condition     = var.admin_identity == "" || can(regex("^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+$", var.admin_identity))
    error_message = "Admin identity must be an existing commercial AWS role ARN."
  }
}

variable "report_storage_ref" {
  type    = string
  default = ""
  validation {
    condition     = var.report_storage_ref == "" || can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$", var.report_storage_ref))
    error_message = "Invalid report_storage_ref; only safe report-only pinned runtime inputs and once-daily UTC schedules are supported."
  }
}

variable "schedule" {
  type    = string
  default = "17 3 * * *"
  validation {
    condition     = can(regex("^([0-5]?[0-9]) ([01]?[0-9]|2[0-3]) \\* \\* \\*$", var.schedule))
    error_message = "Invalid schedule; only safe report-only pinned runtime inputs and once-daily UTC schedules are supported."
  }
}

variable "correction" {
  type    = string
  default = "report_only"
  validation {
    condition     = var.correction == "report_only"
    error_message = "Invalid correction; only safe report-only pinned runtime inputs and once-daily UTC schedules are supported."
  }
}

variable "vpc_id" {
  type    = string
  default = ""
}

variable "automator_workdir" {
  type    = string
  default = ""
  validation {
    condition     = var.automator_workdir == "" || can(regex("^/[A-Za-z0-9_/-]+$", var.automator_workdir))
    error_message = "Provide the safe absolute path to the Automator checkout baked into the CodeBuild image."
  }
}

variable "provision" {
  type    = bool
  default = false
}

variable "schedule_enabled" {
  type    = bool
  default = false
}

variable "retries" {
  type    = number
  default = 0
  validation {
    condition     = var.retries >= 0 && var.retries <= 4 && floor(var.retries) == var.retries
    error_message = "retries must be a bounded integer (0..4)."
  }
}

variable "timeout_seconds" {
  type    = number
  default = 300
  validation {
    condition     = var.timeout_seconds >= 300 && var.timeout_seconds <= 900 && var.timeout_seconds % 60 == 0
    error_message = "CodeBuild timeout_seconds must be 300..900 in whole minutes."
  }
}

variable "max_attempts_per_day" {
  type    = number
  default = 1
  validation {
    condition     = var.max_attempts_per_day >= 1 && var.max_attempts_per_day <= 5 && floor(var.max_attempts_per_day) == var.max_attempts_per_day
    error_message = "max_attempts_per_day must be a bounded integer (1..5)."
  }
}

variable "subnet_ids" {
  type    = list(string)
  default = []
}

variable "security_group_ids" {
  type    = list(string)
  default = []
}

