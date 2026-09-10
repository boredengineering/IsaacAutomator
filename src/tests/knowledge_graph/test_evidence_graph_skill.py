"""Repository skill contract, links and documented CLI syntax (no live services)."""
import contextlib
import argparse
import io
from pathlib import Path
import re
import shlex
import unittest
from unittest.mock import patch

import yaml

from src.knowledge_graph.cli import main

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / '.agents/skills/isaac-automator/evidence-graph/SKILL.md'
GUIDE = ROOT / '.agents/references/docs/evidence-graph-agent-guide.md'
BRIEF = ROOT / 'ai/evidence-graph.agent.md'
PLAN = ROOT / '.agents/references/plans/evidence-graph-agent-skill-plan.md'


class EvidenceGraphSkillTests(unittest.TestCase):
    def test_skill_contract_and_discovery(self):
        self.assertTrue(SKILL.is_file(), 'Evidence graph skill must exist')
        text = SKILL.read_text()
        self.assertTrue(text.startswith('---\n'))
        metadata = yaml.safe_load(text.split('---', 2)[1])
        self.assertEqual(metadata['name'], 'isaac-automator-evidence-graph')
        self.assertLessEqual(len(metadata['description']), 60)
        self.assertTrue(metadata['description'].endswith('.'))
        self.assertEqual(metadata['platforms'], ['linux'])
        self.assertEqual(metadata['license'], 'Apache-2.0')
        self.assertTrue(metadata['author'])
        self.assertRegex(metadata['version'], r'^\d+\.\d+\.\d+$')
        for heading in ('When to Use', 'Prerequisites', 'Procedure', 'Safety boundaries',
                        'Answer contract', 'Pitfalls', 'Verification'):
            self.assertIn('## ' + heading, text)
        self.assertIn('ai/evidence-graph.agent.md',
                      (ROOT / 'src/knowledge_graph/README.md').read_text())
        self.assertIn('evidence-graph/SKILL.md', BRIEF.read_text())
        self.assertIn('advisory', BRIEF.read_text())

    def test_artifact_relative_links_resolve(self):
        for path in (SKILL, GUIDE, BRIEF, PLAN):
            self.assertTrue(path.is_file(), str(path))
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' in target or target.startswith('#'):
                    continue
                resolved = (path.parent / target.split('#')[0]).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT))
                self.assertTrue(resolved.exists(), (path, target))

    def test_documented_graph_commands_parse(self):
        # Stop immediately after real argument parsing, before any side effects.
        class Parsed(Exception):
            pass

        original = argparse.ArgumentParser.parse_args

        def parse_only(parser, args=None, namespace=None):
            original(parser, args, namespace)
            raise Parsed

        commands = 0
        for path in (SKILL, GUIDE):
            self.assertTrue(path.is_file(), str(path))
            text = path.read_text()
            examples = re.findall(r'`(\./knowledge-graph [^\n`]+)`', text)
            examples += re.findall(r'^(\./knowledge-graph [^\n]+)$', text, re.MULTILINE)
            for command in examples:
                args = shlex.split(command)
                if not args:
                    continue
                commands += 1
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()), \
                        patch.object(argparse.ArgumentParser, 'parse_args', parse_only), \
                        self.assertRaises(Parsed):
                    main(args[1:])
        self.assertGreater(commands, 10)
