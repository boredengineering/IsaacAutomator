"""Structural Python-format placeholders, never expand an inventory."""
import re
import string


FIELD = re.compile(r"[A-Za-z_]\w*(?:\[[A-Za-z_]\w*\])*")


def parse(result, path, text):
    section = "unknown"
    for line, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            section = raw[1:-1]
        if not section.endswith(":vars") or "=" not in raw or raw.startswith("#"):
            continue
        key, template = raw.split("=", 1)
        key = key.strip()
        if not FIELD.fullmatch(key):
            continue
        entity = result.entity(path, section + "/" + key, "InventoryField", key, line)
        for index, (_, field, spec, conversion) in enumerate(string.Formatter().parse(template)):
            if field is None:
                continue
            if FIELD.fullmatch(field) and not spec and not conversion:
                result.claim(entity, "transports_field", field, path, line,
                             extractor="automator-inventory/v1", occurrence=index)
            else:
                result.coverage(path, "unresolved", "inventory_dynamic_format")
