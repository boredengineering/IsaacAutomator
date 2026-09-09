# ECR is opt-in; no repository is created or destroyed by the workstation.
variable "enable_ecr" {
  description = "Attach a dedicated ECR pull role and require IMDSv2."
  type        = bool
  default     = false
  nullable    = false
}

variable "ecr_account_id" {
  description = "Account owning the existing ECR repository."
  type        = string
  default     = ""
  nullable    = false
  validation {
    condition     = var.ecr_account_id == "" || can(regex("^[0-9]{12}$", var.ecr_account_id))
    error_message = "ecr_account_id must be exactly 12 digits."
  }
}

variable "ecr_region" {
  description = "Commercial AWS region of the existing ECR repository."
  type        = string
  default     = ""
  nullable    = false
  validation {
    condition     = var.ecr_region == "" || (can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.ecr_region)) && !startswith(var.ecr_region, "cn-") && !startswith(var.ecr_region, "us-gov-"))
    error_message = "ecr_region must be a commercial AWS region (not China or GovCloud)."
  }
}

variable "ecr_repository" {
  description = "Exact repository name, including any namespace path."
  type        = string
  default     = ""
  nullable    = false
  validation {
    condition     = var.ecr_repository == "" || (length(var.ecr_repository) >= 2 && length(var.ecr_repository) <= 256 && can(regex("^[a-z0-9]+(?:[._/-][a-z0-9]+)*$", var.ecr_repository)))
    error_message = "ecr_repository must be a 2-256 character lowercase ECR repository path, without wildcards."
  }
}
