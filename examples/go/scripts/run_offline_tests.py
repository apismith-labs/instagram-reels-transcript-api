#!/usr/bin/env python3
"""Run Go tests without cache and enforce discovery/count safeguards."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINIMUM_TEST_EXECUTIONS = 98


def go_json_stream(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    values = []
    offset = 0
    while offset < len(text):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset == len(text):
            break
        value, offset = decoder.raw_decode(text, offset)
        values.append(value)
    return values


def check_test_file_discovery() -> set[Path]:
    discovered = {
        path.resolve()
        for path in ROOT.rglob("*_test.go")
        if "vendor" not in path.parts and ".git" not in path.parts
    }
    listing = subprocess.run(
        ["go", "list", "-test", "-json", "./..."],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if listing.returncode:
        sys.stderr.write(listing.stderr)
        raise RuntimeError("go list could not verify test-file discovery")
    included: set[Path] = set()
    for package in go_json_stream(listing.stdout):
        package_dir = Path(package.get("Dir", ROOT))
        for field in ("TestGoFiles", "XTestGoFiles"):
            included.update((package_dir / name).resolve() for name in package.get(field, []))
    missing_paths, unexpected_paths = compare_test_files(discovered, included)
    if missing_paths or unexpected_paths:
        missing = sorted(str(path.relative_to(ROOT)) for path in missing_paths)
        unexpected = sorted(str(path) for path in unexpected_paths)
        raise RuntimeError(f"test file discovery mismatch; omitted={missing}; unexpected={unexpected}")
    if not discovered:
        raise RuntimeError("no Go test files were discovered")
    print(f"Go test files discovered and included: {len(discovered)}")
    return discovered


def compare_test_files(discovered: set[Path], included: set[Path]) -> tuple[set[Path], set[Path]]:
    return discovered - included, included - discovered


def test_count_gate(run_count: int, pass_count: int, skip_count: int, fail_count: int) -> bool:
    return run_count >= MINIMUM_TEST_EXECUTIONS and pass_count == run_count and skip_count == 0 and fail_count == 0


class GateSelfTests(unittest.TestCase):
    def test_minimum_count_boundary(self) -> None:
        self.assertFalse(test_count_gate(MINIMUM_TEST_EXECUTIONS - 1, MINIMUM_TEST_EXECUTIONS - 1, 0, 0))
        self.assertTrue(test_count_gate(MINIMUM_TEST_EXECUTIONS, MINIMUM_TEST_EXECUTIONS, 0, 0))
        self.assertTrue(test_count_gate(MINIMUM_TEST_EXECUTIONS + 1, MINIMUM_TEST_EXECUTIONS + 1, 0, 0))

    def test_skip_and_failure_are_rejected(self) -> None:
        self.assertFalse(test_count_gate(MINIMUM_TEST_EXECUTIONS, MINIMUM_TEST_EXECUTIONS - 1, 1, 0))
        self.assertFalse(test_count_gate(MINIMUM_TEST_EXECUTIONS, MINIMUM_TEST_EXECUTIONS - 1, 0, 1))

    def test_test_file_omission_is_detected(self) -> None:
        discovered = {Path("a_test.go"), Path("new_test.go")}
        included = {Path("a_test.go")}
        missing, unexpected = compare_test_files(discovered, included)
        self.assertEqual(missing, {Path("new_test.go")})
        self.assertFalse(unexpected)


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GateSelfTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if sys.argv[1:]:
        print("usage: python3 scripts/run_offline_tests.py [--self-test]", file=sys.stderr)
        return 2
    try:
        check_test_file_discovery()
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"Go test gate failed: {error}", file=sys.stderr)
        return 1

    result = subprocess.run(
        ["go", "test", "./...", "-count=1", "-json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        print(f"Go test process exited {result.returncode}", file=sys.stderr)
        return result.returncode or 1

    try:
        events = go_json_stream(result.stdout)
    except json.JSONDecodeError as error:
        print(f"Go test JSON could not be parsed: {error}", file=sys.stderr)
        return 1
    runs = [event for event in events if event.get("Action") == "run" and event.get("Test")]
    passed = [event for event in events if event.get("Action") == "pass" and event.get("Test")]
    skipped = [event for event in events if event.get("Action") == "skip" and event.get("Test")]
    failures = [event for event in events if event.get("Action") == "fail"]
    print(f"Go test executions: {len(runs)}; passed: {len(passed)}; skipped: {len(skipped)}; failed: {len(failures)}")
    if not test_count_gate(len(runs), len(passed), len(skipped), len(failures)):
        if len(runs) < MINIMUM_TEST_EXECUTIONS:
            print(f"Go test count gate failed: {len(runs)} < {MINIMUM_TEST_EXECUTIONS}", file=sys.stderr)
            return 1
        print("Go test result gate failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
