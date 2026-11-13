import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('image_policy', Path(__file__).resolve().parents[1] / 'tools/check_image_report.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class ImagePolicy(unittest.TestCase):
    def test_fixable_high_and_critical_are_blocking(self):
        rows = [{'Severity': severity, 'FixedVersion': '2'} for severity in ('HIGH', 'CRITICAL', 'LOW')]
        findings, fixed, unresolved = policy.evaluate({'Results': [{'Class': 'os-pkgs', 'Vulnerabilities': rows}]})
        self.assertEqual(len(findings), 3)
        self.assertEqual(len(fixed), 2)
        self.assertEqual(unresolved, [])

    def test_unfixed_vulnerabilities_remain_visible(self):
        rows = [{'Severity': 'HIGH'}, {'Severity': 'CRITICAL', 'FixedVersion': ''}]
        findings, fixed, unresolved = policy.evaluate({'Results': [{'Class': 'os-pkgs', 'Vulnerabilities': rows}]})
        self.assertEqual(len(findings), 2)
        self.assertEqual(fixed, [])
        self.assertEqual(len(unresolved), 2)

    def test_missing_operating_system_scan_fails_closed(self):
        for value in ({}, {'Results': []}, {'Results': [{'Class': 'lang-pkgs'}]}):
            with self.assertRaises(ValueError):
                policy.evaluate(value)


if __name__ == '__main__':
    unittest.main()
