"""Bounded YAML syntax only; aliases, merges and custom tags unsupported."""
import yaml
from yaml.nodes import MappingNode, SequenceNode, ScalarNode


def compose(text):
    depth = count = 0
    for event in yaml.parse(text, Loader=yaml.SafeLoader):
        count += 1
        if count > 20000 or isinstance(event, yaml.AliasEvent):
            raise ValueError("yaml_bound_or_alias")
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
        if depth > 64:
            raise ValueError("yaml_depth")
        tag = getattr(event, "tag", None)
        if tag and tag not in {"tag:yaml.org,2002:" + t for t in
                               ("str", "null", "bool", "int", "float", "timestamp", "seq", "map")}:
            raise ValueError("yaml_tag")
    root = yaml.compose(text, Loader=yaml.SafeLoader)

    def validate(node):
        if isinstance(node, MappingNode):
            keys = set()
            for key, value in node.value:
                if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
                    raise ValueError("yaml_key")
                if key.value in keys or key.value == "<<":
                    raise ValueError("yaml_duplicate_or_merge")
                keys.add(key.value)
                validate(value)
        elif isinstance(node, SequenceNode):
            for value in node.value:
                validate(value)
    validate(root)
    return root


def mapping(node):
    return dict((k.value, v) for k, v in node.value) if isinstance(node, MappingNode) else {}


def scalar(node, default=""):
    return node.value if isinstance(node, ScalarNode) else default


def sequence(node):
    return node.value if isinstance(node, SequenceNode) else []
