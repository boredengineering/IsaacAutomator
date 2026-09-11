variable "project" {
  type = string
}
variable "region" {
  type        = string
  description = "Explicit backend storage location, independent of the GPU region."
}
variable "state_bucket_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.state_bucket_name)) && var.state_bucket_name != "auto"
    error_message = "Supply an explicit approved bucket name; no implicit auto creation."
  }
}
variable "controller_principal" {
  type = string
  validation {
    condition     = can(regex("^(serviceAccount|user):[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$", var.controller_principal))
    error_message = "Supply one explicit controller user/service account; no public principals."
  }
}
variable "kms_key_name" {
  type        = string
  default     = ""
  description = "Existing CMEK only. Verify storage service-agent KMS permissions separately."
}
