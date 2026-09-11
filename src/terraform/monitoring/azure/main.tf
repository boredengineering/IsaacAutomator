terraform {
  required_version = ">= 1.7, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.30.0"
    }
  }
}
provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
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
      condition     = !var.provision || (alltrue([for value in concat(local.identities, [var.image, var.config_artifact, var.report_storage_ref, var.subscription_id, var.resource_group_name, var.infrastructure_subnet_id]) : value != ""]) && length(distinct(local.identities)) == 3)
      error_message = "Provisioning requires pinned image, baked config artifact, distinct runtime/scheduler/admin identities, externally retained reports, and private subnet configuration."
    }
  }
}
resource "azurerm_container_app_environment" "check" {
  count                          = var.provision ? 1 : 0
  name                           = "${var.name}-private"
  location                       = var.region
  resource_group_name            = var.resource_group_name
  infrastructure_subnet_id       = var.infrastructure_subnet_id
  internal_load_balancer_enabled = true
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
  depends_on = [terraform_data.guard]
}
resource "azurerm_container_app_job" "check" {
  count                        = var.provision ? 1 : 0
  name                         = var.name
  location                     = var.region
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.check[0].id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = var.timeout_seconds
  replica_retry_limit          = var.retries
  identity {
    type         = "UserAssigned"
    identity_ids = [var.runtime_identity]
  }
  registry {
    server   = split("/", var.image)[0]
    identity = var.runtime_identity
  }
  dynamic "manual_trigger_config" {
    for_each = var.schedule_enabled ? [] : [1]
    content {
      parallelism              = 1
      replica_completion_count = 1
    }
  }
  dynamic "schedule_trigger_config" {
    for_each = var.schedule_enabled ? [1] : []
    content {
      cron_expression          = var.schedule
      parallelism              = 1
      replica_completion_count = 1
    }
  }
  template {
    container {
      name    = "drift-check"
      image   = var.image
      command = ["./drift"]
      args    = slice(local.invocation, 1, 4)
      cpu     = 0.5
      memory  = "1Gi"
    }
  }
}
