"""Ansible declaration syntax, not an execution/precedence interpreter."""
import posixpath
import re
from .yaml_source import compose, mapping, scalar, sequence


RESERVED = {"name", "when", "tags", "notify", "listen", "register", "vars", "become",
            "become_user", "delegate_to", "run_once", "loop", "loop_control", "with_items",
            "ignore_errors", "failed_when", "changed_when", "check_mode", "environment",
            "retries", "until", "delay", "args", "no_log", "block", "rescue", "always"}


def strings(node):
    return [scalar(n) for n in sequence(node)] if sequence(node) else ([scalar(node)] if node else [])


def condition(attrs, inherited=()):
    expressions = list(inherited) + strings(attrs.get("when"))
    expressions = [e for e in expressions if e]
    return {"state": "expression" if expressions else "unresolved",
            "expression": " and ".join("(" + e + ")" for e in expressions) if len(expressions) > 1 else "".join(expressions)}


def is_document(path, root):
    return "ansible" in path.split("/") or "roles" in path.split("/") or any("hosts" in mapping(n) for n in sequence(root))


def dynamic(value):
    return not value or any(token in value for token in ("{{", "{%", "{#"))


def unresolved(result, record, reason, occurrence: str | int = "reference"):
    result.coverage(record["path"], "unresolved", reason)
    result.claim(record["id"], "unresolved_reference", reason, record["path"], record["line"],
                 condition={"state": "unresolved", "expression": ""}, assessment="unreviewed",
                 occurrence=occurrence, extractor="automator-ansible/v1")


def parse(result, path, text):
    root = compose(text)
    records = []
    if mapping(root):
        result.coverage(path, "unsupported", "ansible_non_task_mapping")
        return records
    parts = path.split("/")
    role = None
    if "roles" in parts and parts.index("roles") + 1 < len(parts):
        role = "/".join(parts[:parts.index("roles") + 2])

    def emit(subject, predicate, value, node, cond, **kwargs):
        result.claim(subject, predicate, value, path, node.start_mark.line + 1,
                     max(node.start_mark.line + 1, node.end_mark.line), condition=cond,
                     extractor="automator-ansible/v1", **kwargs)

    def tags(subject, attrs, inherited, node, cond):
        values = inherited + strings(attrs.get("tags"))
        for index, tag in enumerate(values):
            emit(subject, "has_tag", tag, node, cond, occurrence=index)
        return values

    def tasks(nodes, owner, anchor, inherited=(), inherited_tags=None, handlers=False, owner_scope=None):
        for index, node in enumerate(sequence(nodes)):
            attrs = mapping(node)
            key = anchor + "/task:" + str(index)
            task = result.entity(path, key, "HandlerDefinition" if handlers else "TaskDefinition",
                                 scalar(attrs.get("name"), key), node.start_mark.line + 1)
            cond = condition(attrs, inherited)
            emit(owner, "contains_task", task, node, cond, iri=True)
            task_tags = tags(task, attrs, inherited_tags or [], node, cond)
            modules = [k for k in attrs if k not in RESERVED and not k.startswith("with_")]
            if len(modules) == 1:
                emit(task, "invokes_module", modules[0], node, cond)
                result.coverage(path, "unsupported", "ansible_arguments_not_analyzed")
                if "{{" in text or "{%" in text:
                    result.coverage(path, "unresolved", "ansible_argument_templates_not_resolved")
            else:
                result.coverage(path, "unsupported", "ansible_action_shape")
            records.append({"id": task, "path": path, "line": node.start_mark.line + 1,
                            "role": role, "owner": owner_scope or role or owner,
                            "handler": handlers, "name": scalar(attrs.get("name")),
                            "listen": strings(attrs.get("listen")), "notify": strings(attrs.get("notify")),
                            "condition": cond})
            for action in modules:
                if action.split(".")[-1] in {"include_tasks", "import_tasks", "include_role", "import_role"}:
                    value = attrs[action]
                    target = scalar(value) or scalar(mapping(value).get("name")) or scalar(mapping(value).get("file"))
                    records[-1]["include"] = target
                    unresolved(result, records[-1], "ansible_dynamic_reference" if dynamic(target) else "ansible_include_not_resolved")
            if "block" in attrs:
                tasks(attrs["block"], task, key + "/block", list(inherited) + strings(attrs.get("when")),
                      task_tags, handlers, owner_scope or role or owner)
            for unsupported in ("rescue", "always", "loop", "with_items"):
                if unsupported in attrs:
                    result.coverage(path, "unsupported", "ansible_" + unsupported + "_not_evaluated")

    if role and ("tasks" in parts or "handlers" in parts):
        file_id = result.entity(path, "task-file", "AnsibleTaskFile", parts[-1])
        tasks(root, file_id, "file", handlers="handlers" in parts)
        return records

    for index, node in enumerate(sequence(root)):
        attrs = mapping(node)
        if "hosts" not in attrs:
            result.coverage(path, "unsupported", "ansible_document_shape")
            continue
        key = "play:" + str(index)
        play = result.entity(path, key, "AnsiblePlay", scalar(attrs.get("name"), key), node.start_mark.line + 1)
        cond = condition(attrs)
        play_tags = tags(play, attrs, [], node, cond)
        for role_index, entry in enumerate(sequence(attrs.get("roles"))):
            fields = mapping(entry)
            target = scalar(entry) or scalar(fields.get("role"))
            invocation_key = key + "/role:" + str(role_index)
            invocation = result.entity(path, invocation_key, "RoleInvocation",
                                       "dynamic role" if dynamic(target) else target, entry.start_mark.line + 1)
            invocation_condition = condition(fields, strings(attrs.get("when")))
            emit(play, "contains_role_invocation", invocation, entry, invocation_condition, iri=True)
            tags(invocation, fields, play_tags, entry, invocation_condition)
            records.append({"id": invocation, "path": path, "line": entry.start_mark.line + 1,
                            "role": None, "owner": play, "handler": False, "notify": [],
                            "target_role": target, "condition": invocation_condition})
        for section in ("pre_tasks", "tasks", "post_tasks"):
            tasks(attrs.get(section), play, key + "/" + section, strings(attrs.get("when")), play_tags)
        tasks(attrs.get("handlers"), play, key + "/handlers", strings(attrs.get("when")), play_tags, handlers=True)
    return records


def resolve(result, records):
    roles, names, topics = {}, {}, {}
    for record in records:
        role = record["role"]
        if role and role not in roles:
            roles[role] = result.entity(record["path"], "role:" + role, "AnsibleRole", role.split("/")[-1])
        if role:
            result.claim(roles[role], "contains_handler" if record["handler"] else "contains_task",
                         record["id"], record["path"], record["line"], iri=True,
                         condition=record["condition"], extractor="automator-ansible/v1")
        if record["handler"]:
            names.setdefault((record["owner"], record["name"]), []).append(record["id"])
            for topic in record["listen"]:
                topics.setdefault((record["owner"], topic), []).append(record["id"])
    for record in records:
        if "target_role" in record:
            target = record["target_role"]
            directory = posixpath.dirname(record["path"])
            role_id = roles.get(posixpath.join(directory, "roles", target)) if re.fullmatch(r"[\w.-]+", target) else None
            if role_id:
                result.claim(record["id"], "uses_role", role_id, record["path"], record["line"],
                             iri=True, condition=record["condition"], extractor="automator-ansible/v1")
            else:
                unresolved(result, record, "ansible_dynamic_reference" if dynamic(target) else "ansible_role_not_admitted")
        for index, notice in enumerate(record["notify"]):
            named = names.get((record["owner"], notice), [])
            listening = topics.get((record["owner"], notice), [])
            if dynamic(notice) or len(named) > 1 or (named and listening and set(named) != set(listening)):
                unresolved(result, record, "ansible_dynamic_or_ambiguous_handler", index)
                continue
            targets = listening or named
            if not targets:
                unresolved(result, record, "ansible_handler_not_admitted", index)
            for target in targets:
                result.claim(record["id"], "notifies", target, record["path"], record["line"],
                             iri=True, condition=record["condition"], occurrence=index,
                             extractor="automator-ansible/v1")
