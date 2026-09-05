variable "prefix" {
  type = string
}

variable "deployment_name" {
  type = string
}

variable "public_key_openssh" {
  type = string
}

variable "instance_type" {
  type = string
}

variable "gpu_count" {
  type = number
}

variable "gpu_type" {
  type = string
}

variable "ssh_port" {
  type = number
}

variable "isaac_enabled" {
  type    = bool
  default = false
}

variable "ingress_cidrs" {
  type = list(string)
}

variable "boot_disk_type" {
  type = string
}

variable "os_username" {
  type = string
}

variable "region" {
  type = string
}

variable "from_image" {
  type    = bool
  default = false
}

# Project that owns the prebuilt Isaac Automator image. Defaults to the
# deployment project, but can be overridden if the image lives elsewhere.
variable "image_project" {
  type = string
}

variable "use_flex_start" {
  description = "Deploy using GCP Flex-start (Dynamic Workload Scheduler)"
  type        = bool
  default     = false
}

variable "security_profile" {
  description = "Security profile tier: simple, team, or enterprise"
  type        = string
  default     = "simple"
}

variable "project" {
  description = "GCP Project ID"
  type        = string
  default     = ""
}

variable "enable_cmek" {
  description = "Whether CMEK is active"
  type        = bool
  default     = false
}

variable "enable_iap_only" {
  description = "Zero public IP; instances are private and accessed via Cloud IAP TCP forwarding"
  type        = bool
  default     = false
}

variable "enable_oslogin" {
  description = "Enforce Google Cloud OS Login instead of metadata SSH keys"
  type        = bool
  default     = false
}

variable "kms_compute_disk_key_link" {
  description = "Self link to KMS CryptoKey for boot disk encryption"
  type        = string
  default     = ""
}

