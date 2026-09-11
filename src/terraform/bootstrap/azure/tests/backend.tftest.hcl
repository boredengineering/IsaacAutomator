mock_provider "azurerm" {
  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/backend-rg"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/examplestate"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      resource_manager_id = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/backend-rg/providers/Microsoft.Storage/storageAccounts/examplestate/blobServices/default/containers/tfstate"
    }
  }
}

variables {
  tenant_id                = "11111111-1111-1111-1111-111111111111"
  subscription_id          = "11111111-1111-1111-1111-111111111111"
  region                   = "eastus"
  resource_group_name      = "backend-rg"
  storage_account_name     = "examplestate"
  container_name           = "tfstate"
  controller_principal     = "22222222-2222-2222-2222-222222222222"
  workload_resource_groups = ["workload-rg"]
}

run "protected_storage" {
  command = plan
  assert {
    condition     = azurerm_storage_account.state.https_traffic_only_enabled && azurerm_storage_account.state.min_tls_version == "TLS1_2" && !azurerm_storage_account.state.allow_nested_items_to_be_public && !azurerm_storage_account.state.shared_access_key_enabled
    error_message = "Require Entra, HTTPS/TLS and no public blob access."
  }
  assert {
    condition     = azurerm_storage_account.state.blob_properties[0].versioning_enabled && azurerm_storage_account.state.blob_properties[0].delete_retention_policy[0].days == 7 && azurerm_storage_account.state.infrastructure_encryption_enabled
    error_message = "Encryption, versioning and soft-delete required."
  }
  assert {
    condition     = azurerm_storage_container.state.container_access_type == "private" && azurerm_management_lock.state.lock_level == "CanNotDelete"
    error_message = "Private container and account delete protection required."
  }
  assert {
    condition     = azurerm_role_assignment.controller.role_definition_name == "Storage Blob Data Contributor" && azurerm_role_assignment.controller.principal_id == var.controller_principal
    error_message = "Grant only explicit controller blob data access."
  }
}

run "reject_workload_parent" {
  command = plan
  variables {
    workload_resource_groups = ["BACKEND-RG"]
  }
  expect_failures = [azurerm_resource_group.backend]
}
