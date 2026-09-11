mock_provider "azurerm" {
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/monitoring/providers/Microsoft.App/managedEnvironments/drift-private"
    }
  }
}

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

run "explicit_activation" {
  command = plan
  variables { schedule_enabled = true }
  assert {
    condition     = length(azurerm_container_app_job.check[0].manual_trigger_config) == 0 && azurerm_container_app_job.check[0].schedule_trigger_config[0].cron_expression == "17 3 * * *"
    error_message = "Only an explicit second activation flag may schedule the report-only job."
  }
}
run "missing_report_reference" {
  command = plan
  variables { report_storage_ref = "" }
  expect_failures = [terraform_data.guard]
}
run "missing_pinned_config" {
  command = plan
  variables { config_artifact = "" }
  expect_failures = [terraform_data.guard]
}
run "retired_runtime" {
  command = plan
  variables { provision = false }
  assert {
    condition     = output.runtime_name == null && output.report_storage_ownership == "external_retained"
    error_message = "Retirement leaves no runtime and does not own or delete reports."
  }
}
