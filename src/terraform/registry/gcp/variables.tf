variable "kms_key_name" {
  description = "Optional existing CMEK CryptoKey resource ID; key lifecycle is managed separately."
  type        = string
  default     = ""
  validation {
    condition     = var.kms_key_name == "" || can(regex("^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+$", var.kms_key_name))
    error_message = "kms_key_name must be empty or an existing projects/.../locations/.../keyRings/.../cryptoKeys/... resource ID."
  }
}

variable "publisher_members" {
  description = "Explicit IAM members granted writer on this repository only."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([
      for member in var.publisher_members :
      can(regex("^(serviceAccount:|user:|group:|principal://|principalSet://)[^[:space:]]+$", member))
    ])
    error_message = "Publishers must be explicit serviceAccount, user, group, principal, or principalSet identities; public/domain-wide grants are not allowed."
  }
}

variable "project" {
  description = "Explicit project owning this durable repository."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project))
    error_message = "project must be an explicit GCP project ID."
  }
}

variable "location" {
  description = "Regional Artifact Registry location (not a multi-region)."
  type        = string
  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.location))
    error_message = "location must be a GCP region, for example us-central1."
  }
}

variable "repository" {
  description = "Docker repository ID, not an image path or URL."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9_-]{0,62}$", var.repository))
    error_message = "repository must start with a lowercase letter and contain at most 63 lowercase letters, digits, underscores, or hyphens."
  }
}
