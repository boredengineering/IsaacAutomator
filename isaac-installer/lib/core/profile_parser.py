#!/usr/bin/env python3
"""Legacy installer YAML -> NUL-delimited key/value data, never shell source.

Requires PyYAML in the installer's python3 environment (OS package python3-yaml,
or `python3 -m pip install PyYAML` in a virtual environment). Parsing failures
never fall back to a partial/token-based interpretation of the document.
"""
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required to load installer profiles. Install the OS package "
             "python3-yaml, or run `python3 -m pip install PyYAML` in your Python "
             "environment, then retry. No profile was applied.")


class ProfileLoader(yaml.SafeLoader):
    """Safe YAML with explicit keys only; no overwrites or merge-key precedence."""

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            if key_node.tag != "tag:yaml.org,2002:str":
                raise ValueError("Profile keys must be strings; YAML merge keys are unsupported.")
            key = self.construct_object(key_node, deep=deep)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Invalid profile key: {key!r}; use letters, digits and underscores.")
            if key in mapping:
                raise ValueError(f"Duplicate profile key: {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def parse_profile(path):
    with open(path, encoding="utf-8") as stream:
        data = yaml.load(stream, Loader=ProfileLoader)
    if not isinstance(data, dict) or not data:
        raise ValueError("Expected a non-empty legacy profile mapping.")
    # Legacy public presets have no kind. Never interpret newer schemas as defaults.
    for key, value in data.items():
        if key.upper() == "KIND":
            if value == "workstation-baseline":
                raise ValueError("Workstation baseline is an inventory, not an executable installer profile.")
            raise ValueError("Unsupported installer profile kind; use a kind-less legacy installer preset. "
                             "workstation-profile documents require a separate adapter.")
    items = []
    names = set()
    active = set()

    def flatten(node, prefix="CFG_"):
        if id(node) in active:
            raise ValueError("Recursive YAML aliases are unsupported.")
        active.add(id(node))
        for key, value in node.items():
            name = prefix + key.upper()
            if name in names:
                raise ValueError(f"Colliding flattened profile key: {name}")
            names.add(name)
            if isinstance(value, dict):
                flatten(value, name + "_")
            else:
                if not isinstance(value, (str, bool, int, float)):
                    raise ValueError(f"Expected a string, boolean or number for {name}.")
                text = "true" if value is True else "false" if value is False else str(value)
                if "\0" in text:
                    raise ValueError(f"NUL characters cannot be exported for {name}.")
                items.extend((name, text))
        active.remove(id(node))

    flatten(data)
    return b"".join(item.encode("utf-8") + b"\0" for item in items)


def main():
    try:
        payload = parse_profile(sys.argv[1])
    except yaml.YAMLError:
        # PyYAML diagnostics may include private source text, tags and filenames.
        print("Invalid installer profile: Malformed or unsupported YAML; check syntax and tags.",
              file=sys.stderr)
        return 1
    except OSError:
        print("Invalid installer profile: Cannot read profile; check that it is an existing "
              "readable file and verify access permissions.", file=sys.stderr)
        return 1
    except (ValueError, RecursionError) as error:
        print(f"Invalid installer profile: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
