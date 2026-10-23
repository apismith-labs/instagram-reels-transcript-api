#!/usr/bin/env python3
"""Run Java's offline JUnit suite and fail closed on stale or invalid reports."""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from typing import Callable

# Keep equal to the current full Surefire execution count (including parameterized cases).
MINIMUM_TEST_EXECUTIONS = 126

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
    return (
        found > 0
        and totals["tests"] >= minimum
        and totals["failures"] == 0
        and totals["errors"] == 0
        and totals["skipped"] == 0
        and not problems
    )


def report_directory(module_root: pathlib.Path) -> pathlib.Path:
    """Return the one permitted cleanup target after rejecting symlinks/escapes."""
    root = module_root.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"Maven module root is not a directory: {root}")
    target = root / "target"
    reports = target / "surefire-reports"
    for path in (target, reports):
        if path.is_symlink():
            raise RuntimeError(f"refusing symlink in Surefire report path: {path}")
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"Surefire report path escapes Maven module: {path}") from exc
    if target.exists() and not target.is_dir():
        raise RuntimeError(f"Maven target path is not a directory: {target}")
    if reports.exists() and not reports.is_dir():
        raise RuntimeError(f"Surefire reports path is not a directory: {reports}")
    return reports


def clear_reports(module_root: pathlib.Path, remover: Callable = shutil.rmtree) -> pathlib.Path:
    reports = report_directory(module_root)
    if reports.exists():
        remover(reports)
    if reports.exists():
        raise RuntimeError(f"failed to remove Surefire reports directory: {reports}")
    return reports


def execute_gate(
    module_root: pathlib.Path,
    command: list[str],
    runner: Callable = subprocess.run,
    remover: Callable = shutil.rmtree,
) -> int:
    """Run Maven only after safe cleanup; never inspect reports after Maven failure."""
    root = module_root.resolve(strict=True)
    try:
        clear_reports(root, remover=remover)
    except (OSError, RuntimeError) as exc:
        print(f"Test gate cleanup failed closed: {exc}", file=sys.stderr)
        return 1

    proc = runner(command, cwd=root, check=False)
    if proc.returncode != 0:
        print(f"Maven test process failed with exit code {proc.returncode}; preserving failure", file=sys.stderr)
        return 1

    try:
        current_reports = report_directory(root)
    except (OSError, RuntimeError) as exc:
        print(f"Test gate report path check failed closed: {exc}", file=sys.stderr)
        return 1
    reports = sorted(current_reports.glob("TEST-*.xml")) if current_reports.exists() else []
    totals, problems, found = parse_reports(reports)
    print(
        f"Java JUnit executions: {totals['tests']} (minimum {MINIMUM_TEST_EXECUTIONS}); "
        f"failures={totals['failures']}; errors={totals['errors']}; "
        f"skipped={totals['skipped']}; reports={found}"
    )
    for problem in problems:
        print(f"TEST FAILURE: {problem}", file=sys.stderr)
    if not validate(totals, problems, found):
        if totals["tests"] < MINIMUM_TEST_EXECUTIONS:
            print("Test count gate failed: actual executions are below the enforced minimum", file=sys.stderr)
        if found == 0:
            print("Test count gate failed: no fresh Surefire XML reports were found", file=sys.stderr)
        return 1
    return 0


def synthetic_report(destination: pathlib.Path, tests: int, *, failures: int = 0, errors: int = 0, skipped: int = 0) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "TEST-current.xml").write_text(
        f'<testsuite name="current" tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"/>',
        encoding="utf-8",
    )


def self_test() -> int:
    root = ET.fromstring(SAMPLE)
    totals = {k: int(root.attrib[k]) for k in ("tests", "failures", "errors", "skipped")}
    checks = [
        validate(totals, [], 1, 3),
        not validate(totals, [], 1, 4),
        not validate({**totals, "failures": 1}, [], 1, 3),
        not validate({**totals, "errors": 1}, [], 1, 3),
        not validate({**totals, "skipped": 1}, [], 1, 3),
        not validate(totals, [], 0, 3),
    ]

    with tempfile.TemporaryDirectory(prefix="java-test-gate-") as raw:
        module = pathlib.Path(raw) / "module"
        reports = module / "target" / "surefire-reports"
        module.mkdir()

        # A removed test class used to leave a stale 126-execution report beside a fresh 115 report.
        synthetic_report(reports, MINIMUM_TEST_EXECUTIONS)
        def deleted_class_runner(command, *, cwd, check):
            assert not (cwd / "target" / "surefire-reports" / "TEST-current.xml").exists()
            synthetic_report(cwd / "target" / "surefire-reports", 115)
            return SimpleNamespace(returncode=0)

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            deleted_class_failed = execute_gate(module, ["fake-mvn", "test"], runner=deleted_class_runner) == 1
        checks.append(deleted_class_failed and "115 (minimum 126)" in out.getvalue())

        # Maven failure cannot be hidden by a pre-existing passing report.
        synthetic_report(reports, MINIMUM_TEST_EXECUTIONS)

        def failed_maven_runner(command, *, cwd, check):
            return SimpleNamespace(returncode=1)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            checks.append(execute_gate(module, ["fake-mvn", "test"], runner=failed_maven_runner) == 1)

        # Cleanup errors fail closed and must prevent Maven from starting.
        synthetic_report(reports, MINIMUM_TEST_EXECUTIONS)
        started = []

        def forbidden_runner(command, *, cwd, check):
            started.append(True)
            return SimpleNamespace(returncode=0)

        def failing_remover(_path):
            raise OSError("injected cleanup failure")

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cleanup_failed = execute_gate(
                module, ["fake-mvn", "test"], runner=forbidden_runner, remover=failing_remover
            ) == 1
        checks.append(cleanup_failed and not started)

        # A fresh normal run at the enforced threshold passes and reports exactly 126.
        def passing_runner(command, *, cwd, check):
            synthetic_report(cwd / "target" / "surefire-reports", MINIMUM_TEST_EXECUTIONS)
            return SimpleNamespace(returncode=0)

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            normal_passed = execute_gate(module, ["fake-mvn", "test"], runner=passing_runner) == 0
        checks.append(normal_passed and f"{MINIMUM_TEST_EXECUTIONS} (minimum {MINIMUM_TEST_EXECUTIONS})" in out.getvalue())

        # An unexpected symlink at the exact cleanup target is rejected without following it.
        outside = pathlib.Path(raw) / "outside"
        outside.mkdir()
        target = module / "target"
        if target.exists():
            shutil.rmtree(target)
        target.symlink_to(outside, target_is_directory=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            symlink_rejected = execute_gate(module, ["fake-mvn", "test"], runner=forbidden_runner) == 1
        checks.append(symlink_rejected and not started)

    if all(checks):
        print("Java test gate self-test: PASS (validation, stale reports, deleted-class threshold, Maven failure, cleanup failure, fresh 126, symlink rejection)")
        return 0
    print(f"Java test gate self-test: FAIL ({sum(checks)}/{len(checks)} checks passed)", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    module_root = pathlib.Path(__file__).resolve().parents[1]
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
    return execute_gate(module_root, command)


if __name__ == "__main__":
    raise SystemExit(main())
