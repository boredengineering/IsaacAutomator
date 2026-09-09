variable "enable_artifact_registry" {
  description = "Opt in to pulling from an existing private Artifact Registry repository."
  type        = bool
  default     = false
}

variable "artifact_registry_project" {
  description = "Explicit project owning the existing repository (may differ from the VM project)."
  type        = string
  default     = ""
}

variable "artifact_registry_location" {
  description = "Region of the existing Artifact Registry repository."
  type        = string
  default     = ""
}

variable "artifact_registry_repository" {
  description = "Existing Docker repository ID, not a URL or image path."
  type        = string
  default     = ""
}
