# prefix for created resources and tags
# full name looks like <prefix>.<deployment_name>.<app_name>.<resource_type>
variable "prefix" {
  type = string
}

variable "deployment_name" {
  type = string
}

variable "from_image" {
  default = false
  type    = bool
}

variable "ssh_port" {
  type = number
}

variable "zone" {
  type = string
}

variable "project" {
  type = string
}

variable "isaac_workstation_enabled" {
  default = false
  type    = bool
}

variable "isaac_workstation_instance_type" {
  type = string
}

variable "isaac_workstation_gpu_count" {
  type = number
}

variable "isaac_workstation_gpu_type" {
  # "nvidia-tesla-t4" or "nvidia-l4"
  type = string
}

variable "ingress_cidrs" {
  type = list(string)
}

variable "boot_disk_type" {
  type    = string
  default = "pd-ssd"
  validation {
    condition     = contains(["pd-ssd", "hyperdisk-balanced"], var.boot_disk_type)
    error_message = "boot_disk_type must be one of: pd-ssd, hyperdisk-balanced."
  }
}

variable "os_username" {
  type    = string
  default = "ubuntu"
}

variable "use_flex_start" {
  description = "Deploy using GCP Flex-start (Dynamic Workload Scheduler) to improve capacity availability"
  type        = bool
  default     = false
}

variable "use_spot" {
  description = "Deploy using GCP Spot VM (preemptible with 60-91% discount)"
  type        = bool
  default     = false
}

# ------------------------------------------------------------------------------
# Security, Storage & Zero-Trust Variables (Dynamic Feature Flags)
# ------------------------------------------------------------------------------

variable "enable_cmek" {
  description = "Enable Customer-Managed Encryption Keys (Cloud KMS CMEK) for disks and storage"
  type        = bool
  default     = false
}

variable "enable_iap_only" {
  description = "Enforce Zero Public IP; instances are private and accessed via Cloud IAP TCP forwarding"
  type        = bool
  default     = false
}

variable "enable_oslogin" {
  description = "Enforce Google Cloud OS Login with mandatory 2FA instead of static metadata SSH keys"
  type        = bool
  default     = false
}

variable "enable_secrets" {
  description = "Provision and manage credentials in Google Secret Manager"
  type        = bool
  default     = false
}

variable "state_bucket" {
  description = "GCS bucket name for remote Terraform state backend (empty for local state)"
  type        = string
  default     = ""
}

variable "ngc_api_key" {
  description = "NVIDIA NGC API Key for container registries and Omniverse"
  type        = string
  default     = ""
  sensitive   = true
}

variable "hf_token" {
  description = "Hugging Face User Access Token for model checkpoint downloads"
  type        = string
  default     = ""
  sensitive   = true
}

variable "wandb_api_key" {
  description = "Weights & Biases API Key for robotics experiment logging"
  type        = string
  default     = ""
  sensitive   = true
}

