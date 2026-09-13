"""Synthetic v2.16.3 Go-struct protocol fixtures, NEVER real pricing evidence.

Contract source: infracost/cli v2.16.3 internal/format/json.go. Authenticated
pricing integration is opt-in and blocked without the user-provided token.
"""
import json
import unittest


def resource(name, components=None, **options):
    return {'name': name, 'type': 'google_compute_disk', 'is_supported': True,
            'is_free': False, 'metadata': {}, 'cost_components': components or [], **options}


def output(resources):
    return {'currency': 'USD', 'projects': [{'project_name': 'CANARY', 'path': '/CANARY',
            'finops_results': [], 'resources': resources}]}


class ContractTests(unittest.TestCase):
    def test_free_parent_cannot_hide_paid_or_unknown_components(self):
        from src.python.cost_estimate import normalize_scan
        paid = {'price': '10', 'quantity': '1', 'total_monthly_cost': '10'}
        for parent in (resource('x', is_free=True, subresources=[resource('paid', [paid])]),
                       resource('x', is_free=True, subresources=[resource('unknown')]),
                       resource('x', [paid], is_free=True)):
            with self.subTest(parent=parent), self.assertRaises(ValueError):
                normalize_scan(output([parent]))
        valid = resource('x', is_free=True, subresources=[resource('free', is_free=True)])
        self.assertEqual(normalize_scan(output([valid]))['counts']['free'], 1)

    def test_resource_types_and_coverage_metadata_render_without_raw_names(self):
        from src.python.cost_estimate import normalize_scan, format_report
        report = normalize_scan(output([resource('CANARY', is_free=True), resource('other', type='CANARY', is_supported=False)]))
        self.assertEqual(report['resources'][0]['resource_type'], 'google_compute_disk')
        self.assertEqual(report['resources'][1]['resource_type'], 'other')
        for style in ('table', 'json', 'markdown'):
            text = format_report(report, style)
            self.assertNotIn('CANARY', text)
            self.assertIn('google_compute_disk', text)
            self.assertIn(report['timestamp'], text)

    def test_empty_diagnostics_duplicate_and_flex_never_claim_complete(self):
        from src.python.cost_estimate import normalize_scan
        for raw in (output([]), {'currency': 'USD', 'projects': []},
                    output([resource('x')])):
            self.assertEqual(normalize_scan(raw)['status'], 'partial')
        raw = output([resource('a', is_free=True), resource('a', is_free=True)])
        self.assertEqual(normalize_scan(raw)['counts']['free'], 1)
        raw['projects'][0]['diagnostics'] = [{'severity': 'critical', 'message': 'CANARY'}]
        report = normalize_scan(raw)
        self.assertEqual(report['status'], 'partial')
        self.assertNotIn('CANARY', json.dumps(report))
        raw = output([resource('g4', [{'unit': 'hours', 'price': '1', 'quantity': '730', 'total_monthly_cost': '730'}],
                              type='google_compute_instance')])
        report = normalize_scan(raw, flex_unverified=True)
        self.assertEqual(report['status'], 'partial')
        self.assertIsNone(report['resources'][0]['monthly_cost'])
        self.assertEqual(report['counts']['unpriced'], 1)

    def test_v2_recursive_costs_missing_prices_and_free_are_distinct(self):
        from src.python.cost_estimate import normalize_scan
        raw = output([resource('a', [{'unit': 'GB', 'price': '0.1', 'quantity': '1', 'total_monthly_cost': '0.1'}],
                               subresources=[resource('disk', [{'unit': 'GB', 'price': '0.2', 'quantity': '1', 'total_monthly_cost': '0.2'}])]),
                      resource('b', is_free=True), resource('c', is_supported=False),
                      resource('d', [{'unit': 'hours', 'price': '1'}])])
        report = normalize_scan(raw)
        self.assertEqual(report['covered_subtotal'], '0.3')
        self.assertEqual(report['counts'], dict(priced=1, free=1, unpriced=1, unknown=1))
        self.assertEqual(report['status'], 'partial')
        self.assertNotIn('CANARY', json.dumps(report))
        with self.assertRaises(ValueError):
            normalize_scan({'projects': [{'breakdown': {'resources': []}}]})


if __name__ == '__main__':
    unittest.main()
