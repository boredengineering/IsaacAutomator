import unittest
from src.tests.knowledge_graph.test_extractors import snapshot, extract, claims


class AnsibleTests(unittest.TestCase):
    def test_unanalyzed_role_metadata_and_argument_templates_are_explicit(self):
        result = extract(snapshot({
            "ansible/roles/web/meta/main.yml": "dependencies: [other]\n",
            "ansible/roles/web/tasks/main.yml": "- debug:\n    msg: '{{ dynamic_value }}'\n  loop: '{{ items }}'\n",
        }))
        reasons = {c["reason"] for c in result["coverage"]}
        self.assertIn("ansible_non_task_mapping", reasons)
        self.assertIn("ansible_argument_templates_not_resolved", reasons)
        self.assertIn("ansible_loop_not_evaluated", reasons)
        self.assertFalse(claims(result, "consumed_by"))

    def test_nested_block_notify_preserves_guards_and_rejects_ambiguous_handlers(self):
        result = extract(snapshot({"ansible/site.yml": '''- hosts: all
  tasks:
    - block:
        - debug: {}
          when: child_enabled
          notify: restart
      when: parent_enabled
    - debug: {}
      notify: missing
    - debug: {}
      notify: '{{ handler }}'
    - debug: {}
      notify: duplicate
  handlers:
    - name: restart
      debug: {}
    - name: duplicate
      debug: {}
    - name: duplicate
      debug: {}
'''}))
        notices = claims(result, "notifies")
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["condition"]["expression"], "(parent_enabled) and (child_enabled)")
        unresolved = claims(result, "unresolved_reference")
        self.assertEqual(len(unresolved), 3)
        self.assertTrue(all(c["assessment"] == "unreviewed" for c in unresolved))

    def test_role_invocations_keep_conditions_and_dynamic_includes_unresolved(self):
        result = extract(snapshot({
            "ansible/site.yml": "- hosts: all\n  roles:\n    - role: web\n      when: first\n      tags: [gpu]\n    - role: web\n      when: second\n    - role: '{{ selected_role }}'\n  tasks:\n    - include_tasks: '{{ selected_file }}'\n",
            "ansible/roles/web/tasks/main.yml": "- debug: {}\n",
        }))
        invocations = [e for e in result["entities"] if e["kind"] == "RoleInvocation"]
        self.assertEqual(len(invocations), 3)
        uses = claims(result, "uses_role")
        self.assertEqual(len(uses), 2)
        self.assertEqual({c["condition"]["expression"] for c in uses}, {"first", "second"})
        unresolved = claims(result, "unresolved_reference")
        self.assertEqual(len(unresolved), 2)
        self.assertTrue(all(c["assessment"] == "unreviewed" for c in unresolved))
        self.assertIn("ansible_dynamic_reference", {c["reason"] for c in result["coverage"]})

    def test_same_named_roles_resolve_notify_listen_in_owner_scope(self):
        sources = {}
        for root in ("a/ansible", "b/ansible"):
            sources[root + "/roles/web/tasks/main.yml"] = "- name: install\n  debug: {}\n  when: enabled\n  notify: restart topic\n"
            sources[root + "/roles/web/handlers/main.yml"] = "- name: restart first\n  debug: {}\n  listen: restart topic\n- name: restart second\n  debug: {}\n  listen: restart topic\n"
        result = extract(snapshot(sources))
        entities = {e["id"]: e for e in result["entities"]}
        self.assertEqual(len([e for e in entities.values() if e["kind"] == "AnsibleRole"]), 2)
        self.assertEqual(len([e for e in entities.values() if e["kind"] == "HandlerDefinition"]), 4)
        notices = claims(result, "notifies")
        self.assertEqual(len(notices), 4)
        for notice in notices:
            self.assertEqual(entities[notice["subject"]]["path"].split("/")[0], entities[notice["object"]["value"]]["path"].split("/")[0])
            self.assertEqual(notice["condition"]["expression"], "enabled")
        self.assertEqual(extract(snapshot(dict(reversed(list(sources.items()))))), result)

    def test_same_hosts_plays_and_same_names_tasks_are_distinct_with_conditions(self):
        result = extract(snapshot({"ansible/site.yaml": '''- name: first
  hosts: all
  tags: [deploy]
  tasks:
    - name: install
      ansible.builtin.debug: {msg: not-exported}
      when: enabled
      tags: [gpu]
    - name: install
      ansible.builtin.debug: {msg: not-exported}
      when: other
- name: second
  hosts: all
  tasks:
    - name: install
      ansible.builtin.debug: {}
'''}))
        plays = [e for e in result["entities"] if e["kind"] == "AnsiblePlay"]
        tasks = [e for e in result["entities"] if e["kind"] == "TaskDefinition"]
        self.assertEqual(len(plays), 2)
        self.assertEqual(len(tasks), 3)
        self.assertEqual(len({e["id"] for e in tasks}), 3)
        modules = claims(result, "invokes_module")
        self.assertEqual(len(modules), 3)
        self.assertEqual({c["condition"]["expression"] for c in modules}, {"enabled", "other", ""})
        self.assertEqual({c["object"]["value"] for c in claims(result, "has_tag")}, {"gpu", "deploy"})
        self.assertNotIn("not-exported", str(result))
        self.assertEqual(extract(snapshot({"ansible/site.yaml": "- hosts: all\n  tasks: []\n"}))["entities"][0]["kind"], "AnsiblePlay")


if __name__ == "__main__":
    unittest.main()
