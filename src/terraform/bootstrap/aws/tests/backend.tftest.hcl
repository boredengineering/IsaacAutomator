mock_provider "aws" {}

variables {
  bucket_name          = "example-state-test"
  region               = "us-east-1"
  owner_account_id     = "123456789012"
  key_prefix           = "isaacautomator/v2"
  controller_principal = "arn:aws:iam::123456789012:role/controller"
}

run "protected_storage" {
  command = plan
  assert {
    condition     = !aws_s3_bucket.state.force_destroy && aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "State must survive ordinary deletion and retain versions."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.state.block_public_acls && aws_s3_bucket_public_access_block.state.block_public_policy && aws_s3_bucket_public_access_block.state.ignore_public_acls && aws_s3_bucket_public_access_block.state.restrict_public_buckets
    error_message = "Public access must be blocked."
  }
  assert {
    condition     = aws_s3_bucket_ownership_controls.state.rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "Bucket owner must own objects; ACLs disabled."
  }
  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "State must be encrypted."
  }
  assert {
    condition     = strcontains(aws_s3_bucket_policy.state.policy, "aws:SecureTransport") && strcontains(output.controller_policy_json, "*.tflock")
    error_message = "TLS and scoped native locking permissions required."
  }
}

run "invalid_bucket" {
  command = plan
  variables {
    bucket_name = "auto"
  }
  expect_failures = [var.bucket_name]
}
