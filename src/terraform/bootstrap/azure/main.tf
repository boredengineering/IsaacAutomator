# Independent admin stack. Its resource group must never belong to a workload.
terraform {
  required_version = ">= 1.7.0, < 2.0.0"
  backend "local" {}
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 4.30.0"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
  tenant_id                       = var.tenant_id
  subscription_id                 = var.subscription_id
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

resource "azurerm_resource_group" "backend" {
  name     = var.resource_group_name
  location = var.region
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = length(var.workload_resource_groups) > 0 && !contains([for name in var.workload_resource_groups : lower(name)], lower(var.resource_group_name))
      error_message = "Backend resource group must be outside all workload resource group ownership."
    }
  }
}

resource "azurerm_storage_account" "state" {
  name                              = var.storage_account_name
  resource_group_name               = azurerm_resource_group.backend.name
  location                          = azurerm_resource_group.backend.location
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  account_kind                      = "StorageV2"
  is_hns_enabled                    = false
  https_traffic_only_enabled        = true
  min_tls_version                   = "TLS1_2"
  allow_nested_items_to_be_public   = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  infrastructure_encryption_enabled = true
  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container" "state" {
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_role_assignment" "controller" {
  scope                = azurerm_storage_container.state.resource_manager_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.controller_principal
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_management_lock" "state" {
  name       = "backend-retirement-requires-review"
  scope      = azurerm_storage_account.state.id
  lock_level = "CanNotDelete"
  notes      = "Admin-owned Terraform backend; retirement is separate from workload teardown."
  lifecycle {
    prevent_destroy = true
  }
}
