"""In-memory contract tests; never import or execute target sources."""
import hashlib
import importlib
import unittest
from unittest import mock
from contextlib import ExitStack



def snapshot(sources, repo_id="fixture"):
    return {
        "schema_version": "automator-snapshot/v1", "repo_id": repo_id,
        "snapshot_id": "urn:ia:snapshot:" + "0" * 64,
        "policy_digest": "1" * 64, "sources": sources,
        "manifest": {p: hashlib.sha256(t.encode()).hexdigest() for p, t in sources.items()},
        "coverage": [],
    }


def extract(data):
    try:
        module = importlib.import_module("src.knowledge_graph.extractors.structural")
    except ImportError as exc:
        raise AssertionError("extractor API not implemented") from exc
    return module.extract(data)


def claims(result, predicate):
    return [c for c in result["claims"] if c["predicate"] == "urn:ia:" + predicate]


def round_trip(result, data):
    from rdflib import Dataset
    from src.knowledge_graph.model import build_dataset, claims_from_dataset
    from src.knowledge_graph.projection import project

    dataset = build_dataset(result["claims"], data, "urn:ia:activity:collision-test",
                            entities=result["entities"])
    restored = Dataset().parse(data=dataset.serialize(format="trig"), format="trig")
    return claims_from_dataset(restored), project(restored)


class PythonExtractionTests(unittest.TestCase):
    def test_nested_unresolved_lookup_occurrences_survive_rdf_projection(self):
        data = snapshot({"lookup.py": "p[key][key]\n"})
        result = extract(data)
        unresolved = claims(result, "unresolved_reference")
        self.assertEqual(len(unresolved), 2)
        with self.subTest(stage="extraction"):
            self.assertEqual(len({c["occurrence"] for c in unresolved}), 2)
        restored, graph = round_trip(result, data)
        with self.subTest(stage="rdf_projection"):
            self.assertEqual(len(restored), 2)
            self.assertEqual(sum(n.get("kind") == "Claim" for _, n in graph.nodes(data=True)), 2)
            self.assertEqual(graph.number_of_edges(), 0)
            self.assertTrue(all(c["condition"]["state"] == "unresolved" for c in restored))

    def test_lookup_segments_preserve_identity_through_rdf_projection(self):
        data = snapshot({"lookup.py": "p['a.b']; p['a']['b']; p.a['b']; p.get('a').get('b'); p['a.b']\n"})
        result = extract(data)
        refs = claims(result, "references_field")
        fields = [e for e in result["entities"] if e["kind"] == "ProfileField"]
        with self.subTest(stage="extraction"):
            self.assertEqual(len(refs), 7)
            self.assertEqual(len(fields), 6)
            self.assertEqual(len({c["object"]["value"] for c in refs}), 6)
        restored, graph = round_trip(result, data)
        with self.subTest(stage="rdf_projection"):
            self.assertEqual(len(restored), 7)
            self.assertEqual(graph.number_of_edges(), 7)
            self.assertEqual(len({c["object"]["value"] for c in restored}), 6)
            target = refs[0]["object"]["value"]
            self.assertEqual(graph.number_of_edges(refs[0]["subject"], target), 2)
        self.assertEqual(extract(data), result)

    def test_extract_performs_no_filesystem_network_or_execution_calls(self):
        api = importlib.import_module("src.knowledge_graph.extractors.structural")
        data = snapshot({
            "safe.py": "import subprocess\nsubprocess.run(['never-run'])\nx = profile.get('security')\n",
            "profile.yml": "workstation: {demos: [demo]}\n",
            "tf/aws/main.tf": 'resource "aws_instance" "vm" {}\n',
            "ansible/site.yml": "- hosts: all\n  tasks:\n    - shell: never-run\n",
        })
        with ExitStack() as stack:
            for target in ("builtins.open", "io.open", "os.open", "os.system", "socket.socket", "subprocess.Popen", "pathlib.Path.read_text", "pathlib.Path.read_bytes"):
                stack.enter_context(mock.patch(target, side_effect=AssertionError("forbidden IO")))
            result = api.extract(data)
        self.assertFalse([c for c in result["coverage"] if c["status"] == "failed"])
        self.assertTrue([e for e in result["entities"] if e["kind"] == "ResourceDeclaration"])

    def test_snapshot_digest_and_parser_size_bounds_fail_closed(self):
        data = snapshot({"source.py": "pass\n"})
        data["manifest"]["source.py"] = "f" * 64
        result = extract(data)
        self.assertFalse(result["entities"])
        self.assertEqual(result["coverage"][0]["status"], "failed")
        oversized = snapshot({"source.py": "#" + "x" * 1_048_576})
        result = extract(oversized)
        self.assertFalse(result["entities"])
        self.assertEqual(result["coverage"][0]["status"], "failed")

    def test_parse_failures_are_bounded_and_do_not_export_partial_or_errors(self):
        for path, text in [
            ("bad.py", "def broken(: PRIVATE_ERROR_LITERAL"),
            ("bad.yaml", "x: &a [*a]"),
            ("bad.yaml", "x: !!python/object/apply:os.system ['PRIVATE_ERROR_LITERAL']"),
            ("bad.yaml", "a: 1\na: 2"),
            ("bad.yaml", "x: [" + "[" * 80 + "0" + "]" * 81),
        ]:
            with self.subTest(path=path, text=text[:20]):
                result = extract(snapshot({path: text}))
                self.assertFalse(result["entities"])
                self.assertFalse(result["claims"])
                self.assertEqual(result["coverage"][0]["status"], "failed")
                self.assertNotIn("PRIVATE_ERROR_LITERAL", str(result))

    def test_dynamic_lookup_and_control_flow_stay_unresolved(self):
        result = extract(snapshot({"lookup.py": "def f(profile, key):\n    if enabled:\n        return profile[key]\n    return profile.get('security')\n"}))
        unresolved = claims(result, "unresolved_reference")
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["assessment"], "unreviewed")
        self.assertEqual(unresolved[0]["condition"]["state"], "unresolved")
        refs = claims(result, "references_field")
        self.assertEqual(refs[0]["condition"]["state"], "unresolved")
        self.assertIn("python_control_flow_not_evaluated", {c["reason"] for c in result["coverage"]})

    def test_literal_lookup_is_reference_not_consumed_dataflow(self):
        source = "import nonexistent_target\nraise RuntimeError('never execute')\ndef load(profile):\n    return profile.get('security', {}).get('ssh_enabled')\n"
        data = snapshot({"src/python/config.py": source})
        result = extract(data)
        refs = claims(result, "references_field")
        fields = {e["id"]: e for e in result["entities"] if e["kind"] == "ProfileField"}
        self.assertEqual({c["object"]["kind"] for c in refs}, {"iri"})
        self.assertEqual({fields[c["object"]["value"]]["label"] for c in refs}, {"security", "security.ssh_enabled"})
        self.assertFalse(claims(result, "consumed_by"))
        self.assertTrue(all(c["source"]["sha256"] == data["manifest"]["src/python/config.py"] for c in result["claims"]))
        self.assertTrue(all(c["source"]["line"] == 4 for c in refs))
        self.assertEqual(extract(data), result)
        self.assertNotEqual(extract(snapshot(data["sources"], "other"))["entities"], result["entities"])


if __name__ == "__main__":
    unittest.main()
