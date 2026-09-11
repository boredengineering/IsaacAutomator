variable "tenant_id" {
  type = string
}
variable "subscription_id" {
  type = string
}
variable "region" {
  type = string
}
variable "resource_group_name" {
  type = string
}
variable "workload_resource_groups" {
  type        = list(string)
  description = "Complete workload-owned RG names, including any unrelated workloads sharing this controller. Required even for use-existing doctor."
}
variable "storage_account_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name)) && var.storage_account_name != "auto"
    error_message = "Supply an explicit approved storage account name."
  }
}
variable "container_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.container_name)) && !strcontains(var.container_name, "--")
    error_message = "Supply a valid private container name."
  }
}
variable "controller_principal" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", var.controller_principal))
    error_message = "Supply the Entra object ID (not client/application ID) of the controller principal."
  }
}
