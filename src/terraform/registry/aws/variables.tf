variable "account_id" {
  description = "Repository owner account; the provider refuses any other authenticated account."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be exactly 12 digits."
  }
}

variable "region" {
  description = "Commercial AWS region for the durable repository."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region)) && !startswith(var.region, "cn-") && !startswith(var.region, "us-gov-")
    error_message = "region must be a commercial AWS region (not China or GovCloud)."
  }
}

variable "repository" {
  description = "One exact lowercase ECR repository path."
  type        = string
  nullable    = false
  validation {
    condition     = length(var.repository) >= 2 && length(var.repository) <= 256 && can(regex("^[a-z0-9]+(?:[._/-][a-z0-9]+)*$", var.repository))
    error_message = "repository must be a 2-256 character lowercase ECR repository path, without wildcards."
  }
}

variable "kms_key_arn" {
  description = "Optional existing customer-managed symmetric KMS key ARN; no key is created or destroyed here."
  type        = string
  default     = ""
  nullable    = false
  validation {
    condition     = var.kms_key_arn == "" || can(regex("^arn:aws:kms:[a-z]{2}-[a-z]+-[0-9]+:[0-9]{12}:key/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|mrk-[0-9a-f]{32})$", var.kms_key_arn))
    error_message = "kms_key_arn must be an existing commercial AWS KMS key ARN, not an alias or wildcard."
  }
}

variable "publisher_principal_arns" {
  description = "Explicit existing IAM role/user ARNs authorized to publish to this repository. No account-root or wildcard principals."
  type        = set(string)
  default     = []
  nullable    = false
  validation {
    condition     = alltrue([for arn in var.publisher_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/[A-Za-z0-9+=,.@_-]+(/[A-Za-z0-9+=,.@_-]+)*$", arn))])
    error_message = "publisher_principal_arns must contain explicit IAM role/user ARNs, never root, wildcard, or session principals."
  }
}

variable "reader_principal_arns" {
  description = "Explicit IAM reader role/user ARNs, including owner-approved cross-account workstation roles."
  type        = set(string)
  default     = []
  nullable    = false
  validation {
    condition     = alltrue([for arn in var.reader_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/[A-Za-z0-9+=,.@_-]+(/[A-Za-z0-9+=,.@_-]+)*$", arn))])
    error_message = "reader_principal_arns must contain explicit IAM role/user ARNs, never root, wildcard, or session principals."
  }
}
