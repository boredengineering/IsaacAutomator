mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project    = "images-project"
  location   = "us-central1"
  repository = "workloads"
}

run "reject_public_publishers" {
  command = plan
  variables {
    publisher_members = ["allUsers"]
  }
  expect_failures = [var.publisher_members]
}

run "reject_wrong_region_cmek" {
  command = plan
  variables {
    kms_key_name = "projects/keys-project/locations/us-west1/keyRings/images/cryptoKeys/images"
  }
  expect_failures = [google_artifact_registry_repository.images]
}

run "reject_malformed_cmek" {
  command = plan
  variables {
    kms_key_name = "not-a-key"
  }
  expect_failures = [var.kms_key_name]
}

run "reject_multiregion_repository" {
  command = plan
  variables {
    location = "us"
  }
  expect_failures = [var.location]
}
