"""Conservative static extraction. Input is an already-admitted snapshot.

No target imports, paths opened, includes followed, or interpreters invoked.
"""
import hashlib
from .common import Result
from . import python_source, profile, inventory, terraform, ansible
from .yaml_source import compose


def extract(snapshot: dict) -> dict:
    result = Result(snapshot)
    tf_declarations = []
    ansible_records = []
    for path, text in sorted(snapshot["sources"].items()):
        partial = Result(snapshot)
        try:
            encoded = text.encode("utf-8")
            if len(encoded) > 1_048_576 or hashlib.sha256(encoded).hexdigest() != snapshot["manifest"].get(path):
                raise ValueError("invalid_admitted_source")
            if path.endswith(".py"):
                python_source.parse(partial, path, text)
                partial.coverage(path, "scanned", "python_ast_subset")
            elif path.endswith((".yaml", ".yml")):
                if ansible.is_document(path, compose(text)):
                    ansible_records.extend(ansible.parse(partial, path, text))
                    partial.coverage(path, "scanned", "ansible_declarations_subset")
                else:
                    profile.parse(partial, path, text)
                    partial.coverage(path, "scanned", "profile_fields_only")
            elif path.split("/")[-1] == "inventory.template":
                inventory.parse(partial, path, text)
                partial.coverage(path, "scanned", "inventory_placeholders_only")
            elif path.endswith(".tf"):
                declarations = terraform.parse(partial, path, text)
                tf_declarations.extend(declarations)
                partial.coverage(path, "scanned", "terraform_declarations_subset")
            else:
                partial.coverage(path, "unsupported", "source_format")
        except Exception:
            # Parser diagnostics can contain source literals. Never serialize them.
            result.coverage(path, "failed", "parse_error_or_limit")
            continue
        for key in result.data:
            result.data[key].extend(partial.data[key])
    terraform.resolve(result, tf_declarations)
    ansible.resolve(result, ansible_records)
    return result.data
