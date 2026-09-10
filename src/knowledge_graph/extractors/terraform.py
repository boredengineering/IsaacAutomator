"""Own narrow HCL2 adapter; declarations and syntactic references, not plans.

No upstream iaclens code is incorporated. All resolution is snapshot-local.
"""
import json
import re
import posixpath
from pathlib import PurePosixPath
import hcl2
from lark import Lark

# Load only the pinned dependency grammar, before the worker enters its sandbox.
# Disable Lark's disk/pickle cache: extract() itself performs no filesystem IO.
_PARSER = Lark.open("hcl2.lark", rel_to=hcl2.__file__, parser="lalr",
                    cache=False, propagate_positions=True)


KINDS = {"resource": "ResourceDeclaration", "data": "DataDeclaration",
         "module": "ModuleCall", "variable": "TerraformVariable",
         "output": "TerraformOutput", "locals": "TerraformLocal"}
REFERENCE = re.compile(r"\$\{([A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)+)\}")


def parse(result, path, text):
    document = hcl2.transform(_PARSER.parse(text + "\n"), with_meta=True)
    declarations = []
    for category, groups in document.items():
        if category not in KINDS:
            result.coverage(path, "unsupported", "terraform_block_" + category)
            continue
        if category == "locals":
            groups = [{name: {"value": value, "__start_line__": group["__start_line__"],
                              "__end_line__": group["__end_line__"]}}
                      for group in groups for name, value in group.items() if not name.startswith("__")]
        for group in groups:
            for name, body in group.items():
                blocks = body.items() if category in {"resource", "data"} else [(name, body)]
                for label, attrs in blocks:
                    address = (name + "." + label) if category in {"resource", "data"} else label
                    prefix = {"variable": "var", "resource": "", "locals": "local"}.get(category, category)
                    address = prefix + "." + address if prefix else address
                    line, end = attrs["__start_line__"], attrs["__end_line__"]
                    controls = [k + "=" + str(attrs[k]) for k in ("count", "for_each") if k in attrs]
                    condition = {"state": "expression", "expression": " and ".join(controls)} if controls else None
                    if controls:
                        result.coverage(path, "unsupported", "terraform_instances_not_expanded")
                    entity = result.entity(path, category + ":" + address, KINDS[category], address, line)
                    result.claim(entity, "declares", address, path, line, end,
                                 extractor="automator-hcl/v1")
                    declarations.append({"id": entity, "address": address, "category": category,
                                         "path": path, "line": line, "end": end, "attrs": attrs,
                                         "condition": condition})
    return declarations


def values(value, anchor):
    if isinstance(value, dict):
        for key, child in value.items():
            if not key.startswith("__"):
                yield from values(child, anchor + (("key", key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from values(child, anchor + (("index", index),))
    elif isinstance(value, str):
        yield anchor, value


def unresolved(result, decl, reason, occurrence):
    result.coverage(decl["path"], "unresolved", reason)
    result.claim(decl["id"], "unresolved_reference", reason, decl["path"],
                 decl["line"], decl["end"], assessment="unreviewed", occurrence=occurrence,
                 condition={"state": "unresolved", "expression": ""}, extractor="automator-hcl/v1")


def resolve(result, declarations):
    owners = {}
    modules = {}
    for decl in declarations:
        directory = str(PurePosixPath(decl["path"]).parent)
        key = (directory, decl["address"])
        owners.setdefault(key, []).append(decl)
        if directory not in modules:
            modules[directory] = result.entity(decl["path"], "module-definition",
                                               "TerraformModuleDefinition", directory)
    children = {}
    for decl in declarations:
        if decl["category"] != "module":
            continue
        directory = str(PurePosixPath(decl["path"]).parent)
        source = decl["attrs"].get("source", "")
        if isinstance(source, str) and source.startswith(("./", "../")) and "${" not in source:
            child = posixpath.normpath(posixpath.join(directory, source))
            if child in modules:
                children[decl["id"]] = child
                result.claim(decl["id"], "resolves_module", modules[child], decl["path"],
                             decl["line"], decl["end"], iri=True, extractor="automator-hcl/v1",
                             condition=decl["condition"])
                for argument in decl["attrs"]:
                    if argument.startswith("__") or argument in {"source", "version", "providers", "count", "for_each", "depends_on"}:
                        continue
                    variables = owners.get((child, "var." + argument), [])
                    if len(variables) == 1:
                        result.claim(decl["id"], "forwards_input_to", variables[0]["id"],
                                     decl["path"], decl["line"], decl["end"], iri=True,
                                     occurrence=argument, extractor="automator-hcl/v1", condition=decl["condition"])
        if decl["id"] not in children:
            unresolved(result, decl, "terraform_module_not_admitted", "source")
    for decl in declarations:
        directory = str(PurePosixPath(decl["path"]).parent)
        for attribute, value in decl["attrs"].items():
            if attribute.startswith("__"):
                continue
            if attribute == "dynamic":
                unresolved(result, decl, "terraform_dynamic_block", attribute)
                continue
            for segments, expression in values(value, (("attribute", attribute),)):
                occurrence = json.dumps(segments)
                if ("key", "dynamic") in segments:
                    unresolved(result, decl, "terraform_dynamic_block", occurrence)
                    continue
                match = REFERENCE.fullmatch(expression)
                if not match:
                    if "${" in expression or "%{" in expression:
                        unresolved(result, decl, "terraform_dynamic_expression", occurrence)
                    continue
                reference = match.group(1)
                result.claim(decl["id"], "references_address", reference, decl["path"],
                             decl["line"], decl["end"], occurrence=occurrence,
                             extractor="automator-hcl/v1", condition=decl["condition"])
                parts = reference.split(".")
                address = ".".join(parts[:3] if parts[0] == "data" else parts[:2])
                targets = owners.get((directory, address), [])
                if parts[0] == "module" and len(parts) >= 3:
                    child = children.get(targets[0]["id"]) if len(targets) == 1 else None
                    targets = owners.get((child, "output." + parts[2]), [])
                if len(targets) == 1:
                    result.claim(decl["id"], "depends_on" if attribute == "depends_on" else "references",
                                 targets[0]["id"], decl["path"], decl["line"], decl["end"],
                                 iri=True, occurrence=occurrence, extractor="automator-hcl/v1",
                                 condition=decl["condition"])
                else:
                    unresolved(result, decl, "terraform_target_missing_or_ambiguous", occurrence)
