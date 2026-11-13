#!/usr/bin/env python3
"""Fail on fixable high/critical dependencies; display unresolved findings too."""
from collections import Counter
import json
from pathlib import Path
import sys


def evaluate(report):
    results = report.get('Results')
    if not isinstance(results, list) or not any(row.get('Class') == 'os-pkgs' for row in results):
        raise ValueError('The report must contain an operating-system package scan')
    findings = [item for row in results for item in row.get('Vulnerabilities', [])]
    severe = [item for item in findings if item.get('Severity') in ('HIGH', 'CRITICAL')]
    fixed = [item for item in severe if item.get('FixedVersion', '').strip()]
    unresolved = [item for item in severe if not item.get('FixedVersion', '').strip()]
    return findings, fixed, unresolved


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 tools/check_image_report.py image-scan.json')
    try:
        findings, fixed, unresolved = evaluate(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
    except (ValueError, TypeError, KeyError) as exc:
        raise SystemExit('Invalid image scan report: ' + str(exc))
    print('All package findings:', dict(sorted(Counter(row.get('Severity', 'UNKNOWN') for row in findings).items())))
    print(f'Fixable HIGH/CRITICAL package findings: {len(fixed)}')
    print(f'HIGH/CRITICAL without an available fixed version: {len(unresolved)}')
    for row in sorted(fixed + unresolved, key=lambda row: (row['VulnerabilityID'], row['PkgName'])):
        print(row['Severity'], row['VulnerabilityID'], row['PkgName'], row['InstalledVersion'], 'fixed=' + row.get('FixedVersion', 'unavailable'))
    if fixed:
        raise SystemExit(1)
    print('PASS: no fixable HIGH/CRITICAL dependency findings; remaining findings require review')


if __name__ == '__main__':
    main()
