terraform {
  required_version = ">= 1.7, < 2.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "6.37.0"
    }
  }
}
provider "google" {
  project = var.project
  region  = var.region
}
locals {
  invocation = ["./drift", "check", "--config", var.config_artifact]
  identities = [var.runtime_identity, var.scheduler_identity, var.admin_identity]
}
resource "terraform_data" "guard" {
  lifecycle {
    precondition {
      condition     = !var.schedule_enabled || var.provision
      error_message = "Schedule activation requires explicit provision=true."
    }
    precondition {
      condition     = var.max_attempts_per_day >= var.retries + 1
      error_message = "Scheduled-attempt budget must cover initial execution plus retries."
    }
    precondition {
      condition     = !var.provision || (alltrue([for value in concat(local.identities, [var.image, var.config_artifact, var.report_storage_ref, var.project, var.network, var.subnetwork]) : value != ""]) && length(distinct(local.identities)) == 3)
      error_message = "Provisioning requires pinned image, baked config artifact, three distinct existing identities, externally retained reports, and private network configuration."
    }
  }
}
resource "google_cloud_run_v2_job" "check" {
  count               = var.provision ? 1 : 0
  name                = var.name
  location            = var.region
  project             = var.project
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = var.runtime_identity
      timeout         = "${var.timeout_seconds}s"
      max_retries     = var.retries
      containers {
        image   = var.image
        command = ["./drift"]
        args    = slice(local.invocation, 1, 4)
        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }
      }
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = var.network
          subnetwork = var.subnetwork
        }
      }
    }
  }
  depends_on = [terraform_data.guard]
}
resource "google_cloud_scheduler_job" "check" {
  count            = var.provision ? 1 : 0
  name             = var.name
  region           = var.region
  project          = var.project
  schedule         = var.schedule
  time_zone        = "Etc/UTC"
  paused           = !var.schedule_enabled
  attempt_deadline = "180s"
  retry_config {
    retry_count        = 0
    max_retry_duration = "0s"
  }
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project}/locations/${var.region}/jobs/${google_cloud_run_v2_job.check[0].name}:run"
    oauth_token {
      service_account_email = var.scheduler_identity
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}
