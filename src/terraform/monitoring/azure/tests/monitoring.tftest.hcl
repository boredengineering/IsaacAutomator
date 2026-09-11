mock_provider "azurerm" {
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/monitoring/providers/Microsoft.App/managedEnvironments/drift-private"
    }
  }
}

run "reject_identity_urls" {
  command = plan
  variables {
    runtime_identity = "https://user:secret@host"
    admin_identity   = "https://user:secret@host"
  }
  expect_failures = [var.runtime_identity, var.admin_identity]
}

run "disabled_by_default" {
  command = plan
  assert {
    condition     = length(azurerm_container_app_job.check) == 0 && length(azurerm_container_app_environment.check) == 0
    error_message = "Default must provision no runtime, environment or schedule."
  }
}
run "private_report_only_runtime" {
  command = plan
  variables {
    provision                = true
    subscription_id          = "00000000-0000-0000-0000-000000000001"
    resource_group_name      = "monitoring"
    image                    = "example.azurecr.io/automator@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    config_artifact          = "/opt/automator/check.json"
    runtime_identity         = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/monitoring/providers/Microsoft.ManagedIdentity/userAssignedIdentities/drift-reader"
    scheduler_identity       = "platform:container-apps-jobs"
    admin_identity           = "00000000-0000-0000-0000-000000000002"
    report_storage_ref       = "external-retained-reports"
    infrastructure_subnet_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/network/providers/Microsoft.Network/virtualNetworks/private/subnets/jobs"
  }
  assert {
    condition     = azurerm_container_app_environment.check[0].internal_load_balancer_enabled && azurerm_container_app_environment.check[0].infrastructure_subnet_id == var.infrastructure_subnet_id
    error_message = "Runtime must use internal-only environment and explicit subnet."
  }
  assert {
    condition     = length(azurerm_container_app_job.check[0].schedule_trigger_config) == 0 && azurerm_container_app_job.check[0].manual_trigger_config[0].parallelism == 1 && azurerm_container_app_job.check[0].replica_retry_limit == 0
    error_message = "Provisioning must leave job manual, bounded and unscheduled."
  }
  assert {
    condition     = azurerm_container_app_job.check[0].identity[0].identity_ids == toset([var.runtime_identity]) && azurerm_container_app_job.check[0].registry[0].identity == var.runtime_identity
    error_message = "Explicit user identity must authenticate runtime and registry without secrets."
  }
  assert {
    condition     = output.invocation == tolist(["./drift", "check", "--config", "/opt/automator/check.json"]) && output.report_storage_ownership == "external_retained"
    error_message = "Report-only invocation and externally retained storage are required."
  }
}
run "reject_implicit_activation" {
  command = plan
  variables { schedule_enabled = true }
  expect_failures = [terraform_data.guard]
}
run "reject_correction" {
  command = plan
  variables { correction = "approval_required" }
  expect_failures = [var.correction]
}
run "reject_unpinned_image" {
  command = plan
  variables { image = "example/automator:latest" }
  expect_failures = [var.image]
}
run "reject_excess_budget" {
  command = plan
  variables { retries = 4 }
  expect_failures = [terraform_data.guard]
}

run "reject_unsupported_registry" {
  command = plan
  variables { image = "registry.example/automator@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  expect_failures = [var.image]
}

run "reject_pretend_scheduler_identity" {
  command = plan
  variables { scheduler_identity = "user-assigned-scheduler" }
  expect_failures = [var.scheduler_identity]
}
