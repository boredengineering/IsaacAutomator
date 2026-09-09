# Independently operated durable infrastructure, never a workstation module.
terraform {
  required_version = ">= 1.3.5"
  backend "gcs" {}
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.57.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 4.57.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.location
}

provider "google-beta" {
  project = var.project
  region  = var.location
}

resource "google_project_service" "artifact_registry" {
  project            = var.project
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project
  location      = var.location
  repository_id = var.repository
  description   = "Shared private Isaac Automator Docker images"
  format        = "DOCKER"
  kms_key_name  = var.kms_key_name != "" ? var.kms_key_name : null

  depends_on = [google_project_service.artifact_registry, google_kms_crypto_key_iam_member.artifact_registry]

  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = var.kms_key_name == "" || try(split("/", var.kms_key_name)[3] == var.location, false)
      error_message = "The existing CMEK key must be in the same region as the repository."
    }
  }
}
