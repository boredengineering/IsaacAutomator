"""Offline shared trust protocol tests; all sources/keys are disposable fixtures."""
import base64
import hashlib
import json
import subprocess
import tempfile
import traceback
from pathlib import Path
import unittest
from unittest.mock import patch

from src.knowledge_graph import shared_contract as contract


def identity(**changes):
    values = dict(issuer="example-issuer", organization="example-team", repository_id="immutable-42",
                  repository_name="team/public-code", revision="a" * 40,
                  source_manifest={"src/example.py": hashlib.sha256(b"public fixture\n").hexdigest()},
                  policy_digest="b" * 64, extractor_digest="c" * 64,
                  dependencies_digest="d" * 64, dirty=False)
    values.update(changes)
    return contract.portable_identity(**values)


class IdentityTests(unittest.TestCase):
    def test_identity_rejects_dirty_or_malformed_selectors(self):
        for change in ({"dirty": True}, {"dirty": 0}, {"organization": "../other"},
                       {"issuer": "issuer\nother"}, {"repository_id": ""},
                       {"revision": "main"}, {"source_manifest": {"../secret": "a" * 64}},
                       {"source_manifest": {"src/a.py": "bad"}}, {"policy_digest": "bad"},
                       {"schema": "unknown"}, {"checkout_path": "/tmp/a"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                identity(**change)

    def test_every_identity_binding_rejects_a_checkout_mismatch(self):
        for change in ({"issuer": "other"}, {"organization": "other"},
                       {"repository_id": "fork-42"}, {"repository_name": "other/public-code"},
                       {"revision": "e" * 40}, {"source_manifest": {"src/a.py": "f" * 64}},
                       {"policy_digest": "e" * 64}, {"extractor_digest": "e" * 64},
                       {"dependencies_digest": "e" * 64}):
            with self.subTest(change=change):
                other = identity(**change)
                self.assertNotEqual(contract.identity_digest(identity()), contract.identity_digest(other))
                with self.assertRaisesRegex(ValueError, "checkout_mismatch"):
                    contract.require_checkout(identity(), other)
        forged = identity()
        forged["dirty"] = True
        with self.assertRaises(ValueError):
            contract.require_checkout(forged, forged)

    def test_portable_identity_has_no_checkout_location(self):
        with tempfile.TemporaryDirectory() as directory:
            fingerprints = []
            for name in ("checkout-one", "elsewhere-checkout-two"):
                checkout = Path(directory) / name
                (checkout / "src").mkdir(parents=True)
                source = checkout / "src/example.py"
                source.write_bytes(b"public fixture\n")
                fingerprints.append(identity(source_manifest={"src/example.py": hashlib.sha256(source.read_bytes()).hexdigest()}))
            first, second = fingerprints
        self.assertEqual(first, second)
        self.assertEqual(contract.identity_digest(first), contract.identity_digest(second))
        self.assertEqual(contract.require_checkout(first, second), "current_checkout")


class SigningFixture:
    """Ephemeral synthetic publisher, never reads installed key material."""
    def __init__(self, root):
        self.root = Path(root)
        self.private = self.root / "synthetic-key.pem"
        subprocess.run(["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519",
                        "-out", str(self.private)], check=True, capture_output=True)
        public = subprocess.run(["/usr/bin/openssl", "pkey", "-in", str(self.private),
                                 "-pubout", "-outform", "DER"], check=True, capture_output=True).stdout
        self.public = public[-32:]

    def trust(self, **changes):
        options = dict(issuer="example-issuer", organization="example-team",
                       repository_id="immutable-42", repository_name="team/public-code",
                       key_id="fixture-key", public_key=self.public)
        options.update(changes)
        return contract.TrustPolicy(**options)

    def payload(self, **changes):
        selected = identity()
        artifacts = {"dataset.trig": b"# synthetic RDF, deliberately not semantically admitted\n",
                     "manifest.json": contract.canonical_json(selected)}
        descriptors = {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                       for name, data in artifacts.items()}
        result = dict(schema="ia-shared-catalog/v1", identity=selected,
                      artifact_schema="ia-shared-opaque-canonical/v1", artifacts=descriptors,
                      generation=hashlib.sha256(contract.canonical_json(descriptors)).hexdigest(),
                      key_id="fixture-key", catalog_sequence=1, revocation_epoch=1,
                      issued_at=1000, expires_at=1100, revoked_generations=[], revoked_keys=[])
        result.update(changes)
        return result, artifacts

    def sign(self, payload):
        message = self.root / "message"
        message.write_bytes(contract.canonical_json(payload))
        signature = subprocess.run(["/usr/bin/openssl", "pkeyutl", "-sign", "-rawin",
                                    "-inkey", str(self.private), "-in", str(message)],
                                   check=True, capture_output=True).stdout
        return contract.canonical_json({"payload": payload, "signature": base64.b64encode(signature).decode("ascii")})


class SignatureTests(unittest.TestCase):
    def test_crypto_temporary_filesystem_failures_are_source_free(self):
        with tempfile.TemporaryDirectory() as root:
            signer = SigningFixture(root)
            payload, _ = signer.payload()
            signed = signer.sign(payload)
            real_cleanup = tempfile.TemporaryDirectory.cleanup
            def fail_cleanup(directory):
                real_cleanup(directory)
                raise PermissionError(13, "synthetic-private-project-name", "synthetic-private-project-name")
            for owner, operation in ((contract.tempfile, "mkdtemp"), (contract.Path, "touch"),
                                     (contract.Path, "write_bytes"), (tempfile.TemporaryDirectory, "cleanup")):
                def fail(*args, **kwargs):
                    raise OSError(5, "synthetic-private-project-name", "synthetic-private-project-name")
                replacement = fail_cleanup if operation == "cleanup" else fail
                with self.subTest(operation=operation), patch.object(owner, operation, new=replacement):
                    try:
                        contract.verify_envelope(signed, signer.trust(), identity(), now=1001)
                    except contract.VerificationError as error:
                        self.assertEqual(str(error), "signature_capability_unavailable")
                        self.assertIsNone(error.__cause__)
                        self.assertTrue(error.__suppress_context__)
                        self.assertNotIn("synthetic-private-project-name", "".join(traceback.format_exception(error)))
                    else:
                        self.fail("temporary filesystem failure must not authenticate the catalog")
                self.assertEqual(contract.verify_envelope(signed, signer.trust(), identity(), now=1001), payload)

    def test_protocol_json_rejects_float_overflow_and_excessive_nesting(self):
        for raw in (b'{"counter":1e999}', b'{"counter":1.0}', b"[" * 40 + b"0" + b"]" * 40):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                contract.strict_json(raw)

    def test_revocations_and_replay_floor_survive_later_catalogs(self):
        self.assertTrue(hasattr(contract, "Checkpoint"), "replay checkpoint missing")
        with tempfile.TemporaryDirectory() as root:
            signer = SigningFixture(root)
            payload, _ = signer.payload(catalog_sequence=5, revocation_epoch=3)
            signed = signer.sign(payload)
            verified = contract.verify_envelope(signed, signer.trust(), identity(), now=1005)
            checkpoint = contract.Checkpoint.from_verified(verified, now=1005)
            self.assertEqual(contract.verify_envelope(signed, signer.trust(), identity(), now=1005,
                                                      checkpoint=checkpoint), payload)
            for change in ({"catalog_sequence": 4}, {"revocation_epoch": 2},
                           {"expires_at": 1101}, {"catalog_sequence": 6, "issued_at": 999}):
                rejected = dict(payload, **change)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    contract.verify_envelope(signer.sign(rejected), signer.trust(), identity(),
                                             now=1005, checkpoint=checkpoint)
            with self.assertRaisesRegex(ValueError, "clock_rollback"):
                contract.verify_envelope(signed, signer.trust(), identity(), now=1004, checkpoint=checkpoint)
            for pins in ({"minimum_sequence": 6}, {"minimum_revocation_epoch": 4},
                         {"revoked_generations": frozenset({payload["generation"]})},
                         {"revoked_keys": frozenset({"fixture-key"})}):
                with self.subTest(pins=pins), self.assertRaises(ValueError):
                    contract.verify_envelope(signed, signer.trust(**pins), identity(), now=1005)
            with self.assertRaisesRegex(ValueError, "key_revoked"):
                contract.verify_envelope(signed, signer.trust(revoked_keys=frozenset({"fixture-key"})),
                                         identity(), now=1005, allow_revoked=True)
            revoked = dict(payload, catalog_sequence=6, revocation_epoch=4,
                           revoked_generations=[payload["generation"]])
            with self.assertRaisesRegex(ValueError, "revoked"):
                contract.verify_envelope(signer.sign(revoked), signer.trust(), identity(), now=1005)
            authenticated = contract.verify_envelope(signer.sign(revoked), signer.trust(), identity(),
                                                      now=1005, checkpoint=checkpoint, allow_revoked=True)
            remembered = contract.Checkpoint.from_verified(authenticated, now=1005, previous=checkpoint)
            restored = dict(payload, catalog_sequence=7, revocation_epoch=5)
            with self.assertRaisesRegex(ValueError, "revoked"):
                contract.verify_envelope(signer.sign(restored), signer.trust(), identity(),
                                         now=1006, checkpoint=remembered)

    def test_signed_catalog_is_bounded_and_scope_and_lease_checked(self):
        with tempfile.TemporaryDirectory() as root:
            signer = SigningFixture(root)
            for change in ({"schema": "future"}, {"extra": "field"},
                           {"identity": identity(repository_id="fork")},
                           {"identity": identity(extractor_digest="f" * 64)},
                           {"key_id": "unapproved"}, {"issued_at": 1002},
                           {"expires_at": 1001}, {"expires_at": 1000000},
                           {"catalog_sequence": True}, {"revocation_epoch": -1},
                           {"revoked_generations": ["bad"]},
                           {"artifact_schema": "pickle/v1"},
                           {"artifacts": {"../escape": {"sha256": "a" * 64, "size": 3}}},
                           {"generation": "f" * 64}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    payload, _ = signer.payload(**change)
                    contract.verify_envelope(signer.sign(payload), signer.trust(), identity(), now=1001)
            payload, _ = signer.payload()
            signed = signer.sign(payload)
            for bad in (b"[]", b'{"payload":1,"payload":2,"signature":"AA=="}',
                        b'{"payload":NaN,"signature":"AA=="}', b"x" * (1024 * 1024 + 1)):
                with self.subTest(raw=bad[:40]), self.assertRaises(ValueError):
                    contract.verify_envelope(bad, signer.trust(), identity(), now=1001)
            for pins in ({"repository_id": "fork"}, {"issuer": "other"},
                         {"repository_name": "other/public-code"}, {"max_lease_seconds": 0}):
                with self.subTest(pins=pins), self.assertRaises(ValueError):
                    contract.verify_envelope(signed, signer.trust(**pins), identity(), now=1001)
            with self.assertRaisesRegex(ValueError, "capability_unavailable"):
                contract.verify_envelope(signed, signer.trust(openssl="/nonexistent/openssl"), identity(), now=1001)

    def test_real_ed25519_signature_and_pinned_publisher(self):
        self.assertTrue(hasattr(contract, "verify_envelope"), "signature verification missing")
        with tempfile.TemporaryDirectory() as root:
            signer = SigningFixture(root)
            payload, _ = signer.payload()
            signed = signer.sign(payload)
            verified = contract.verify_envelope(signed, signer.trust(), identity(), now=1001)
            self.assertEqual(verified, payload)
            tampered = json.loads(signed)
            tampered["payload"]["catalog_sequence"] = 2
            with self.assertRaisesRegex(ValueError, "signature"):
                contract.verify_envelope(contract.canonical_json(tampered), signer.trust(), identity(), now=1001)
            with self.assertRaises(ValueError):
                contract.verify_envelope(signed, signer.trust(public_key=b"z" * 32), identity(), now=1001)


if __name__ == "__main__":
    unittest.main()
