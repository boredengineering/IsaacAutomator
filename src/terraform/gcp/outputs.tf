output "cloud" {
  value = "gcp"
}

output "isaac_workstation_ip" {
  value = var.isaac_workstation_enabled ? module.isaac_workstation[0].public_ip : "NA"
}

output "isaac_workstation_private_ip" {
  value = var.isaac_workstation_enabled ? module.isaac_workstation[0].private_ip : "NA"
}

output "isaac_workstation_vm_id" {
  value = var.isaac_workstation_enabled ? module.isaac_workstation[0].vm_id : "NA"
}

output "iap_enabled" {
  value = var.enable_iap_only
}

output "oslogin_enabled" {
  value = var.enable_oslogin
}

output "ssh_key" {
  value     = var.enable_oslogin ? "OS_LOGIN_ACTIVE" : tls_private_key.ssh_key.private_key_pem
  sensitive = true
}
