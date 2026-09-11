output "state_bucket_name" {
  value = google_storage_bucket.state_bucket.name
}
output "state_bucket_url" {
  value = google_storage_bucket.state_bucket.url
}
