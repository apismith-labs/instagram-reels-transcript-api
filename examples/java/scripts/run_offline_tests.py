#!/usr/bin/env python3
"""Run Java's offline JUnit suite and fail closed on missing/failed/skipped tests."""
from __future__ import annotations
import argparse
import os
import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ET

# Keep equal to the current full Surefire execution count (including parameterized cases).
MINIMUM_TEST_EXECUTIONS = 110

SAMPLE = b'''<testsuite name="sample" tests="3" failures="0" errors="0" skipped="0">
  <testcase classname="sample" name="one"/><testcase classname="sample" name="two"/><testcase classname="sample" name="three"/>
</testsuite>'''

def parse_reports(paths: list[pathlib.Path]):
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    problems: list[str] = []
    found = 0
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            problems.append(f"cannot parse {path}: {exc}")
            continue
        found += 1
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for suite in suites:
            for key in totals:
                totals[key] += int(suite.attrib.get(key, "0"))
            for case in suite.iter("testcase"):
                for failure in list(case):
                    if failure.tag in {"failure", "error"}:
                        detail = (failure.attrib.get("message") or (failure.text or "")).strip()
                        problems.append(f"{case.attrib.get('classname','')}.{case.attrib.get('name','')}: {detail[:500]}")
    return totals, problems, found

def validate(totals, problems, found, minimum=MINIMUM_TEST_EXECUTIONS):
    return found > 0 and totals["tests"] >= minimum and totals["failures"] == 0 and totals["errors"] == 0 and totals["skipped"] == 0 and not problems

def self_test() -> int:
    root = ET.fromstring(SAMPLE)
    totals = {k: int(root.attrib[k]) for k in ("tests", "failures", "errors", "skipped")}
    checks = [
        validate(totals, [], 1, 3),
        not validate(totals, [], 1, 4),
        not validate({**totals, "failures": 1}, [], 1, 3),
        not validate({**totals, "skipped": 1}, [], 1, 3),
        not validate(totals, [], 0, 3),
    ]
    if all(checks):
        print("Java test gate self-test: PASS (valid, below-minimum, failure, skipped, missing-report)")
        return 0
    print("Java test gate self-test: FAIL", file=sys.stderr)
    return 1

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    command = ["mvn", "-B", "-q"]
    # Local users may point the wrapper at an already approved isolated cache.
    # CI leaves these unset and uses the standard Maven cache/settings.
    settings = os.environ.get("MAVEN_SETTINGS")
    repo = os.environ.get("MAVEN_REPO_LOCAL")
    if settings:
        command.extend(["-s", settings])
    if repo:
        command.append(f"-Dmaven.repo.local={repo}")
    command.append("test")
    proc = subprocess.run(command, check=False)
    if proc.returncode != 0:
        print(f"Maven test process failed with exit code {proc.returncode}; preserving failure", file=sys.stderr)
    reports = sorted(pathlib.Path("target/surefire-reports").glob("TEST-*.xml"))
    totals, problems, found = parse_reports(reports)
    print(f"Java JUnit executions: {totals['tests']} (minimum {MINIMUM_TEST_EXECUTIONS}); failures={totals['failures']}; errors={totals['errors']}; skipped={totals['skipped']}; reports={found}")
    for problem in problems:
        print(f"TEST FAILURE: {problem}", file=sys.stderr)
    if proc.returncode != 0 or not validate(totals, problems, found):
        if totals["tests"] < MINIMUM_TEST_EXECUTIONS:
            print("Test count gate failed: actual executions are below the enforced minimum", file=sys.stderr)
        if found == 0:
            print("Test count gate failed: no Surefire XML reports were found", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
