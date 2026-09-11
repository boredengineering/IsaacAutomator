variable "bucket_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.bucket_name)) && var.bucket_name != "auto"
    error_message = "Supply an approved explicit bucket name; auto is only a proposal."
  }
}
variable "region" {
  type = string
}
variable "owner_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.owner_account_id))
    error_message = "Supply the expected backend account ID."
  }
}
variable "controller_principal" {
  type = string
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9_+=,.@/-]+$", var.controller_principal))
    error_message = "Supply one explicit controller IAM role ARN; no wildcard or VM role."
  }
}
variable "key_prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9_-]+(/[a-z0-9_-]+)*$", var.key_prefix))
    error_message = "Supply a safe explicit state prefix without wildcard."
  }
}
variable "kms_key_id" {
  type    = string
  default = ""
}
