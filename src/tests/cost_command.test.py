"""Cost CLI vertical tracers; no network/pricing in ordinary tests."""
import json
from pathlib import Path
import subprocess
import unittest
import tempfile
from click.testing import CliRunner


class CommandTests(unittest.TestCase):
    def test_region_option_is_documented_as_validation_not_a_pricing_override(self):
        from src.python.cost_command import main
        result = CliRunner().invoke(main, ['estimate', '--help'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('not a pricing override', result.output)
        self.assertIn('unresolved', result.output)

    def test_compare_outputs_decimal_delta_in_all_formats_and_doctor_is_local(self):
        from src.python.cost_command import main
        from src.python.cost_estimate import normalized_report
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('before.json', 'after.json')]
            for path, value in zip(paths, ('1.1', '1.3')):
                path.write_text(json.dumps(normalized_report([{'id': 'a', 'state': 'priced', 'monthly_cost': value}])))
            for style in ('table', 'json', 'markdown'):
                result = runner.invoke(main, ['compare', '--before', str(paths[0]), '--after', str(paths[1]), '--format', style])
                self.assertEqual(result.exit_code, 0, str(result.exception))
                self.assertIn('0.2', result.output)
            result = runner.invoke(main, ['doctor', '--infracost-binary', '/nonexistent/infracost', '--format', 'json'])
            self.assertEqual(result.exit_code, 2)
            self.assertEqual(json.loads(result.output)['reason'], 'binary_missing')

    def test_cli_explicit_modes_and_entrypoint_do_not_require_optional_runtime(self):
        from src.python.cost_command import main
        runner = CliRunner()
        result = runner.invoke(main, ['estimate', '--profile', 'CANARY', '--format', 'json'])
        self.assertEqual(result.exit_code, 2)
        report = json.loads(result.output)
        self.assertEqual(report['reason'], 'profile_not_bound')
        self.assertIsNone(report['covered_subtotal'])
        self.assertNotIn('CANARY', result.output)
        result = subprocess.run([str(Path(__file__).resolve().parents[2] / 'cost'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('doctor', result.stdout)
        self.assertIn('compare', result.stdout)


if __name__ == '__main__':
    unittest.main()
