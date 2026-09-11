"""Offline structural checks; provider-mock tests live in each bootstrap root.

Run Terraform tests in a disposable copy with providers initialized separately.
This file never downloads providers, authenticates, or creates operational state.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent / 'bootstrap'

class BootstrapStacks(unittest.TestCase):
    def test_azure_account_is_outside_workload_ancestor_with_entra_and_locks(self):
        path = ROOT / 'azure' / 'main.tf'
        self.assertTrue(path.is_file(), 'independent Azure bootstrap root missing')
        text = path.read_text()
        for fragment in ['CanNotDelete', 'Storage Blob Data Contributor', 'TLS1_2', 'container_delete_retention_policy', 'delete_retention_policy', 'prevent_destroy = true', 'lower(var.resource_group_name)', 'var.workload_resource_groups']:
            self.assertIn(fragment, text)
        for field in ['https_traffic_only_enabled', 'versioning_enabled', 'storage_use_azuread', 'infrastructure_encryption_enabled']:
            self.assertRegex(text, field+r'\s*=\s*true')
        for field in ['allow_nested_items_to_be_public', 'shared_access_key_enabled', 'is_hns_enabled']:
            self.assertRegex(text, field+r'\s*=\s*false')
        self.assertRegex(text, r'container_access_type\s*=\s*"private"')
        self.assertRegex(text, r'version\s*=\s*"= 4.30.0"')

    def test_gcp_storage_has_independent_ownership_and_durable_protection(self):
        text = (ROOT / 'gcp' / 'main.tf').read_text()
        for fragment in ['prevent_destroy = true', 'roles/storage.objectAdmin', 'controller_principal', '604800', 'days_since_noncurrent_time', 'kms_key_name']:
            self.assertIn(fragment, text)
        self.assertRegex(text, r'force_destroy\s*=\s*false')
        self.assertRegex(text, r'public_access_prevention\s*=\s*"enforced"')
        self.assertRegex(text, r'uniform_bucket_level_access\s*=\s*true')
        self.assertRegex(text, r'version\s*=\s*"= 6.45.0"')
        self.assertNotIn('google_project_iam_member', text)

    def test_aws_independent_protected_storage_and_scoped_lock_iam(self):
        path = ROOT / 'aws' / 'main.tf'
        self.assertTrue(path.is_file(), 'independent AWS bootstrap root missing')
        text = path.read_text()
        for protection in ['force_destroy = false', 'prevent_destroy = true', 'BucketOwnerEnforced', 'AES256', 'aws:SecureTransport', 'Enabled', 's3:DeleteObject', '*.tflock', 's3:prefix', 'allowed_account_ids']:
            self.assertIn(protection, text)
        for field in ['block_public_acls', 'block_public_policy', 'ignore_public_acls', 'restrict_public_buckets']:
            self.assertRegex(text, field+r'\s*=\s*true')
        self.assertNotIn('aws_iam_role_policy_attachment', text)
        self.assertNotIn('workstation', text)
        self.assertRegex(text, r'version\s*=\s*"= 5.100.0"')

if __name__ == '__main__':
    unittest.main()
