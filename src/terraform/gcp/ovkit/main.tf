locals {
  boot_image     = "ubuntu-2204-jammy-v20251023"
  boot_disk_size = 255
  os_username    = var.os_username
}

# Latest image in the family created by ./image-gcp. Only resolved when
# --from-image is true, so deployments that don't use a pre-built image
# can still run in projects with no Isaac Automator images yet.
data "google_compute_image" "prebuilt" {
  count   = var.from_image ? 1 : 0
  family  = "isaac-automator-isaacworkstation"
  project = var.image_project
}

# Dedicated Workstation Service Account (Principle of Least Privilege)
# Only provisioned when security_profile is enterprise or when dedicated SA is required
resource "google_service_account" "workstation_sa" {
  count        = var.security_profile == "enterprise" ? 1 : 0
  account_id   = "${substr(replace(var.prefix, "_", "-"), 0, 26)}-sa"
  display_name = "Isaac Workstation Instance Service Account"
  project      = var.project != "" ? var.project : null
}

resource "google_compute_instance" "default" {
  name           = "${var.prefix}-vm"
  machine_type   = var.instance_type
  enable_display = false

  # allows to change instance type without destroying everything
  allow_stopping_for_update = true

  timeouts {
    create = "60m"
  }

  dynamic "scheduling" {
    for_each = var.use_spot ? [1] : []
    content {
      provisioning_model          = "SPOT"
      instance_termination_action = "STOP"
      preemptible                 = true
      automatic_restart           = false
      on_host_maintenance         = "TERMINATE" # required for GPUs
    }
  }

  dynamic "scheduling" {
    for_each = (!var.use_spot && var.use_flex_start) ? [1] : []
    content {
      provisioning_model          = "FLEX_START"
      instance_termination_action = "STOP"
      automatic_restart           = false
      on_host_maintenance         = "TERMINATE" # required for GPUs

      max_run_duration {
        seconds = 604800 # 7 days max allowed duration
      }
    }
  }

  dynamic "scheduling" {
    for_each = (!var.use_spot && !var.use_flex_start) ? [1] : []
    content {
      provisioning_model  = "STANDARD"
      on_host_maintenance = "TERMINATE" # required for GPUs
    }
  }

  boot_disk {
    auto_delete       = true
    kms_key_self_link = var.kms_compute_disk_key_link != "" ? var.kms_compute_disk_key_link : null

    initialize_params {
      image = var.from_image ? data.google_compute_image.prebuilt[0].self_link : local.boot_image
      size  = local.boot_disk_size
      type  = var.boot_disk_type
    }
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  metadata = merge(
    {
      enable-oslogin            = var.enable_oslogin ? "TRUE" : "FALSE"
      block-project-ssh-keys   = var.enable_oslogin ? "TRUE" : "FALSE"
      disable-legacy-endpoints = "TRUE"
    },
    var.enable_oslogin ? {} : {
      ssh-keys = "${local.os_username}:${var.public_key_openssh}"
    }
  )

  labels = {
    deployment = var.deployment_name
  }

  guest_accelerator {
    type  = var.gpu_type
    count = var.gpu_count
  }

  network_interface {
    network    = google_compute_network.default.self_link
    subnetwork = google_compute_subnetwork.default.self_link

    dynamic "access_config" {
      for_each = var.enable_iap_only ? [] : [1]
      content {
        nat_ip = length(google_compute_address.static_ip) > 0 ? google_compute_address.static_ip[0].address : null
      }
    }
  }

  service_account {
    email  = length(google_service_account.workstation_sa) > 0 ? google_service_account.workstation_sa[0].email : null
    scopes = length(google_service_account.workstation_sa) > 0 ? ["cloud-platform"] : [
      "https://www.googleapis.com/auth/devstorage.read_write",
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring.write",
      "https://www.googleapis.com/auth/servicecontrol",
      "https://www.googleapis.com/auth/service.management.readonly",
      "https://www.googleapis.com/auth/trace.append",
    ]
  }
}
