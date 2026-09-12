# Run from the GCP root after local module initialization.
# Mocked plans only: no credentials, cloud reads, or apply.
mock_provider "google" {}

variables {
  prefix             = "offline-flex"
  deployment_name    = "offline-flex"
  public_key_openssh = "ssh-rsa offline-test"
  instance_type      = "g4-standard-48"
  gpu_count          = 1
  gpu_type           = "nvidia-rtx-pro-6000"
  ssh_port           = 22
  ingress_cidrs      = ["192.0.2.0/24"]
  boot_disk_type     = "hyperdisk-balanced"
  os_username        = "ubuntu"
  region             = "us-central1"
  image_project      = "offline-project"
  project            = "offline-project"
}

run "explicit_flex_runtime_and_timeout" {
  command = plan
  module {
    source = "./ovkit"
  }
  variables {
    use_flex_start              = true
    flex_max_run_seconds        = 600
    flex_create_timeout_seconds = 7500
  }
  assert {
    condition     = google_compute_instance.default.scheduling[0].max_run_duration[0].seconds == 600
    error_message = "Flex runtime must use the independent explicit duration."
  }
  assert {
    condition     = google_compute_instance.default.timeouts.create == "7500s"
    error_message = "Create polling timeout is independent of VM runtime and allocation wait."
  }
}

run "reject_spot_and_flex" {
  command = plan
  module { source = "./ovkit" }
  variables {
    use_flex_start = true
    use_spot       = true
  }
  expect_failures = [google_compute_instance.default]
}

run "reject_zero_runtime" {
  command = plan
  module { source = "./ovkit" }
  variables { flex_max_run_seconds = 0 }
  expect_failures = [var.flex_max_run_seconds]
}

run "reject_runtime_over_seven_days" {
  command = plan
  module { source = "./ovkit" }
  variables { flex_max_run_seconds = 604801 }
  expect_failures = [var.flex_max_run_seconds]
}

run "reject_fractional_runtime" {
  command = plan
  module { source = "./ovkit" }
  variables { flex_max_run_seconds = 1.5 }
  expect_failures = [var.flex_max_run_seconds]
}

run "reject_zero_timeout" {
  command = plan
  module { source = "./ovkit" }
  variables { flex_create_timeout_seconds = 0 }
  expect_failures = [var.flex_create_timeout_seconds]
}

run "reject_timeout_over_local_one_day_limit" {
  command = plan
  module { source = "./ovkit" }
  variables { flex_create_timeout_seconds = 86401 }
  expect_failures = [var.flex_create_timeout_seconds]
}

run "reject_fractional_timeout" {
  command = plan
  module { source = "./ovkit" }
  variables { flex_create_timeout_seconds = 1.5 }
  expect_failures = [var.flex_create_timeout_seconds]
}

run "reject_wrong_g4_gpu_count" {
  command = plan
  module { source = "./ovkit" }
  variables {
    use_flex_start = true
    gpu_count      = 8
  }
  expect_failures = [google_compute_instance.default]
}

run "reject_wrong_g4_gpu_type" {
  command = plan
  module { source = "./ovkit" }
  variables {
    use_flex_start = true
    gpu_type       = "nvidia-l4"
  }
  expect_failures = [google_compute_instance.default]
}

run "reject_wrong_g4_boot_disk" {
  command = plan
  module { source = "./ovkit" }
  variables {
    use_flex_start = true
    boot_disk_type = "pd-ssd"
  }
  expect_failures = [google_compute_instance.default]
}

run "g4_48_private_flex" {
  command = plan
  module { source = "./ovkit" }
  variables {
    use_flex_start  = true
    enable_iap_only = true
    enable_oslogin  = true
  }
  assert {
    condition = (
      google_compute_instance.default.machine_type == "g4-standard-48" &&
      one(google_compute_instance.default.guest_accelerator).count == 1 &&
      one(google_compute_instance.default.guest_accelerator).type == "nvidia-rtx-pro-6000" &&
      google_compute_instance.default.boot_disk[0].initialize_params[0].type == "hyperdisk-balanced" &&
      google_compute_instance.default.boot_disk[0].initialize_params[0].size == 255
    )
    error_message = "The single-GPU G4 shape must retain its exact accelerator and boot disk."
  }
  assert {
    condition = (
      google_compute_instance.default.scheduling[0].provisioning_model == "FLEX_START" &&
      !google_compute_instance.default.scheduling[0].automatic_restart &&
      google_compute_instance.default.scheduling[0].on_host_maintenance == "TERMINATE" &&
      google_compute_instance.default.scheduling[0].instance_termination_action == "STOP" &&
      google_compute_instance.default.scheduling[0].max_run_duration[0].seconds == 604800 &&
      google_compute_instance.default.timeouts.create == "3600s"
    )
    error_message = "Flex defaults must retain STOP termination and the bounded runtime."
  }
  assert {
    condition = (
      length(google_compute_instance.default.network_interface[0].access_config) == 0 &&
      google_compute_instance.default.metadata["enable-oslogin"] == "TRUE" &&
      !contains(keys(google_compute_instance.default.metadata), "ssh-keys") &&
      google_compute_instance.default.shielded_instance_config[0].enable_secure_boot &&
      length(google_compute_router_nat.nat) == 1 &&
      length(data.google_compute_image.prebuilt) == 0 &&
      length(google_artifact_registry_repository_iam_member.reader) == 0 &&
      length(google_service_account.workstation_sa) == 0
    )
    error_message = "Private Flex keeps NAT/OS Login/Shielded settings without unselected image, registry or dedicated identity resources."
  }
}

run "g4_384_flex" {
  command = plan
  module { source = "./ovkit" }
  variables {
    use_flex_start = true
    instance_type  = "g4-standard-384"
    gpu_count      = 8
  }
  assert {
    condition = (
      google_compute_instance.default.machine_type == "g4-standard-384" &&
      one(google_compute_instance.default.guest_accelerator).count == 8 &&
      one(google_compute_instance.default.guest_accelerator).type == "nvidia-rtx-pro-6000" &&
      google_compute_instance.default.boot_disk[0].initialize_params[0].type == "hyperdisk-balanced" &&
      google_compute_instance.default.scheduling[0].provisioning_model == "FLEX_START"
    )
    error_message = "The scale gate must generate eight RTX PRO 6000 GPUs, not a substituted shape."
  }
}

run "standard_defaults_unchanged" {
  command = plan
  module { source = "./ovkit" }
  assert {
    condition = (
      google_compute_instance.default.scheduling[0].provisioning_model == "STANDARD" &&
      google_compute_instance.default.scheduling[0].automatic_restart == null &&
      length(google_compute_instance.default.scheduling[0].max_run_duration) == 0 &&
      google_compute_instance.default.timeouts.create == "60m" &&
      length(google_compute_router_nat.nat) == 0
    )
    error_message = "Standard VM scheduling and create timeout must not change."
  }
}

run "spot_defaults_unchanged" {
  command = plan
  module { source = "./ovkit" }
  variables { use_spot = true }
  assert {
    condition = (
      google_compute_instance.default.scheduling[0].provisioning_model == "SPOT" &&
      google_compute_instance.default.scheduling[0].preemptible &&
      !google_compute_instance.default.scheduling[0].automatic_restart &&
      google_compute_instance.default.scheduling[0].instance_termination_action == "STOP" &&
      length(google_compute_instance.default.scheduling[0].max_run_duration) == 0 &&
      google_compute_instance.default.timeouts.create == "60m"
    )
    error_message = "Spot VM scheduling and create timeout must not change."
  }
}
