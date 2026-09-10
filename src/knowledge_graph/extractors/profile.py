"""YAML field declarations without exporting profile values."""
import json
from yaml.nodes import MappingNode, SequenceNode, ScalarNode
from .yaml_source import compose


def parse(result, path, text):
    document = compose(text)

    def walk(node, prefix="", segments=()):
        if isinstance(node, MappingNode):
            for key, value in node.value:
                if not isinstance(key, ScalarNode):
                    continue
                segment = key.value.replace("\\", "\\\\").replace(".", "\\.")
                name = prefix + "." + segment if prefix else segment
                field_path = segments + (("key", key.value),)
                line = key.start_mark.line + 1
                entity = result.entity(path, ["field", field_path], "ProfileField", name, line)
                result.claim(entity, "field_path", name, path, line, evidence="desired",
                             extractor="automator-profile/v1", occurrence=json.dumps(field_path))
                walk(value, name, field_path)
        elif isinstance(node, SequenceNode):
            for index, value in enumerate(node.value):
                walk(value, prefix + "[" + str(index) + "]", segments + (("index", index),))

    walk(document)
