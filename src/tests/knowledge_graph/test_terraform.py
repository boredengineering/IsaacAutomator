import json
import unittest
from src.tests.knowledge_graph.test_extractors import snapshot, extract, claims, round_trip


class TerraformTests(unittest.TestCase):
    def test_typed_occurrences_preserve_parallel_references_through_rdf_projection(self):
        for value, terminal in [
            ('{"a/b"=var.image,a={b=var.image}}', ["key", "b"]),
            ('{"a/0"=var.image,a=[var.image]}', ["index", 0]),
            ('{"a/0"=var.image,a={"0"=var.image}}', ["key", "0"]),
        ]:
            data = snapshot({"tf/main.tf": 'variable "image" {}\noutput "o" { value = ' + value + ' }\n'})
            result = extract(data)
            refs = claims(result, "references")
            with self.subTest(value=value, stage="extraction"):
                self.assertEqual(len(refs), 2)
                self.assertEqual(len(claims(result, "references_address")), 2)
                self.assertEqual(len({c["occurrence"] for c in refs}), 2)
                paths = [json.loads(c["occurrence"]) for c in refs]
                self.assertEqual(paths[0], [["attribute", "value"], ["key", "a/" + str(terminal[1])]])
                self.assertEqual(paths[1], [["attribute", "value"], ["key", "a"], terminal])
            restored, graph = round_trip(result, data)
            with self.subTest(value=value, stage="rdf_projection"):
                self.assertEqual(len(restored), 6)
                self.assertEqual(graph.number_of_edges(), 6)
                self.assertEqual(graph.number_of_edges(refs[0]["subject"], refs[0]["object"]["value"]), 2)
                self.assertEqual(len(claims({"claims": restored}, "references_address")), 2)
            self.assertEqual(extract(data), result)

    def test_nested_dynamic_blocks_keep_reference_resolution_unresolved(self):
        result = extract(snapshot({"tf/gcp/main.tf": '''variable "image" {}
resource "google_compute_instance" "vm" {
  network_interface {
    dynamic "access_config" {
      for_each = var.interfaces
      content { image = var.image }
    }
  }
}
'''}))
        self.assertFalse(claims(result, "references"))
        self.assertIn("terraform_dynamic_block", {c["reason"] for c in result["coverage"]})

    def test_module_meta_arguments_are_not_forwarded_as_child_inputs(self):
        result = extract(snapshot({
            "tf/main.tf": 'module "vm" { source="./vm" count=1 image="public" }\n',
            "tf/vm/main.tf": 'variable "source" {}\nvariable "count" {}\nvariable "image" {}\n',
        }))
        entities = {e["id"]: e for e in result["entities"]}
        self.assertEqual([entities[c["object"]["value"]]["label"] for c in claims(result, "forwards_input_to")], ["var.image"])

    def test_dynamic_blocks_do_not_fabricate_unconditional_reference_paths(self):
        result = extract(snapshot({"tf/gcp/main.tf": '''variable "image" {}
resource "google_compute_instance" "vm" {
  dynamic "disk" {
    for_each = var.disks
    content { image = var.image }
  }
}
'''}))
        self.assertFalse(claims(result, "references"))
        self.assertIn("terraform_dynamic_block", {c["reason"] for c in result["coverage"]})
        self.assertTrue(claims(result, "unresolved_reference"))

    def test_locals_are_declarations_with_separate_reference_edges(self):
        result = extract(snapshot({"tf/gcp/main.tf": 'variable "image" {}\nlocals { selected = var.image }\nresource "google_compute_instance" "vm" { image = local.selected }\n'}))
        entities = {e["id"]: e for e in result["entities"]}
        local = [e for e in entities.values() if e["kind"] == "TerraformLocal"]
        self.assertEqual(len(local), 1)
        self.assertEqual(local[0]["label"], "local.selected")
        refs = claims(result, "references")
        self.assertEqual(len(refs), 2)
        self.assertEqual({entities[c["object"]["value"]]["kind"] for c in refs}, {"TerraformLocal", "TerraformVariable"})

    def test_dynamic_missing_and_remote_references_never_become_supported_targets(self):
        result = extract(snapshot({"tf/aws/main.tf": '''variable "image" {}
resource "aws_instance" "vm" {
  count = var.enabled ? 1 : 0
  ami = var.image
  user_data = templatefile("unread.tpl", {})
  subnet_id = aws_subnet.absent.id
}
module "remote" { source="example/private/module" }
'''}))
        refs = claims(result, "references")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["condition"]["state"], "expression")
        self.assertIn("count", refs[0]["condition"]["expression"])
        unresolved = claims(result, "unresolved_reference")
        self.assertGreaterEqual(len(unresolved), 3)
        self.assertTrue(all(c["assessment"] == "unreviewed" for c in unresolved))
        reasons = {c["reason"] for c in result["coverage"]}
        self.assertTrue({"terraform_dynamic_expression", "terraform_target_missing_or_ambiguous", "terraform_module_not_admitted", "terraform_instances_not_expanded"} <= reasons)
        self.assertFalse(claims(result, "resolves_module"))
        self.assertNotIn("example/private/module", str(result))

    def test_local_module_calls_resolve_admitted_inputs_and_outputs(self):
        result = extract(snapshot({
            "tf/gcp/main.tf": 'variable "image" {}\nmodule "one" { source="./vm" image=var.image }\nmodule "two" { source="./vm" image=var.image }\noutput "ip" { value=module.one.ip }\n',
            "tf/gcp/vm/main.tf": 'variable "image" {}\noutput "ip" { value="not-exported" }\n',
        }))
        calls = [e for e in result["entities"] if e["kind"] == "ModuleCall"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(claims(result, "resolves_module")), 2)
        forwarding = claims(result, "forwards_input_to")
        self.assertEqual(len(forwarding), 2)
        self.assertEqual(len({c["subject"] for c in forwarding}), 2)
        entities = {e["id"]: e for e in result["entities"]}
        outputs = [c for c in claims(result, "references") if entities[c["object"]["value"]]["kind"] == "TerraformOutput"]
        self.assertEqual(len(outputs), 1)
        self.assertEqual(entities[outputs[0]["object"]["value"]]["path"], "tf/gcp/vm/main.tf")
        self.assertNotIn("not-exported", str(result))

    def test_references_resolve_only_within_module_directory(self):
        data = snapshot({
            "src/terraform/aws/main.tf": 'resource "aws_instance" "vm" {\n ami = var.image\n user_data = var.image\n depends_on = [aws_vpc.net]\n}\nresource "aws_vpc" "net" {}\n',
            "src/terraform/aws/variables.tf": 'variable "image" {}\n',
            "src/terraform/registry/aws/main.tf": 'resource "aws_instance" "vm" { ami = var.image }\nvariable "image" {}\n',
        })
        result = extract(data)
        entities = {e["id"]: e for e in result["entities"]}
        resources = [e for e in entities.values() if e["kind"] == "ResourceDeclaration"]
        self.assertEqual(len(resources), 3)
        refs = claims(result, "references")
        self.assertEqual(len(refs), 3)
        for ref in refs:
            subject, target = entities[ref["subject"]], entities[ref["object"]["value"]]
            self.assertEqual(subject["path"].rsplit("/", 1)[0], target["path"].rsplit("/", 1)[0])
            self.assertEqual(ref["scope"]["cloud"], "aws")
            self.assertEqual(ref["source"]["sha256"], data["manifest"][subject["path"]])
        self.assertEqual(len(claims(result, "depends_on")), 1)
        self.assertEqual(len({c["occurrence"] for c in refs}), 2)
        self.assertEqual(extract(data), result)


if __name__ == "__main__":
    unittest.main()
