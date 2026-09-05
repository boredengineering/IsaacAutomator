output "public_ip" {
  value = length(google_compute_instance.default.network_interface[0].access_config) > 0 ? google_compute_instance.default.network_interface[0].access_config[0].nat_ip : ""
}

output "private_ip" {
  value = google_compute_instance.default.network_interface[0].network_ip
}

output "vm_id" {
  value = google_compute_instance.default.id
}
