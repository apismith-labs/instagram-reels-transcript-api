#!/usr/bin/env python3
"""Run the Rust offline test suite and fail closed on missing or incomplete summaries."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINIMUM_TEST_EXECUTIONS = 86
SUMMARY = re.compile(
    r"test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
    r"(\d+) measured; (\d+) filtered out;"
)


def main() -> int:
    result = subprocess.run(
        ["cargo", "test", "--all-targets", "--locked"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        print(f"Rust test process failed with exit code {result.returncode}.", file=sys.stderr)
        return result.returncode or 1

    summaries = SUMMARY.findall(result.stdout)
    if not summaries:
        print("No Cargo test summary was found; refusing to pass.", file=sys.stderr)
        return 1

    passed = sum(int(row[1]) for row in summaries)
    failed = sum(int(row[2]) for row in summaries)
    ignored = sum(int(row[3]) for row in summaries)
    filtered = sum(int(row[5]) for row in summaries)
    failed_summaries = sum(row[0] != "ok" for row in summaries)
    executed = passed + failed
    print(
        f"Rust test gate: executed={executed}, passed={passed}, "
        f"failed={failed}, ignored={ignored}, filtered={filtered}, "
        f"minimum={MINIMUM_TEST_EXECUTIONS}"
    )
    if (
        executed < MINIMUM_TEST_EXECUTIONS
        or failed
        or ignored
        or filtered
        or failed_summaries
    ):
        print("Rust test count/result gate failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
