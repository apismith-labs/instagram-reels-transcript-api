#!/usr/bin/env python3
"""Run five fail-closed source mutations against focused offline witnesses."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = [
    (
        "single-shot POST",
        "src/execute.rs",
        "Ok(value) => value,",
        "Ok(value) => { let _ = post_run(config, &input); value },",
        ["--test", "single_contract", "successful_result_preserves_run_dataset_build_and_segments"],
        "single-shot POST invariant violated",
    ),
    (
        "URL attribution",
        "src/attribution.rs",
        "if requested.is_some() && output == requested {",
        "if requested.is_some() {",
        ["--test", "single_contract", "h_unmatched_dataset_url_never_leaks_transcript"],
        "unmatched dataset URL must stay unknown",
    ),
    (
        "required charge cap",
        "src/config.rs",
        "let charge_cap = validate_charge_cap(self.charge_cap.as_deref())?;",
        'let charge_cap = self.charge_cap.unwrap_or_else(|| "0.01".to_owned());',
        ["--test", "single_contract", "n_missing_charge_cap_fails_before_transport"],
        "missing charge cap must fail before transport",
    ),
    (
        "output text redaction",
        "src/sanitize.rs",
        "Value::String(s) => Value::String(redact_text(s)),",
        "Value::String(s) => Value::String(s.clone()),",
        ["--lib", "output::tests::persisted_text_secrets_are_absent_and_business_text_is_preserved"],
        "secret persisted",
    ),
    (
        "prefixed credential redaction scope",
        "src/sanitize.rs",
        "if i + w.len() < chars.len() && !is_boundary(chars[i + w.len()]) {",
        "if i > 0 && !is_boundary(chars[i - 1]) { return false; }\n    if i + w.len() < chars.len() && !is_boundary(chars[i + w.len()]) {",
        ["--lib", "output::tests::persisted_prefixed_credentials_are_absent_and_json_stays_intact"],
        "secret persisted",
    ),
]


def run_mutation(
    name: str,
    file_name: str,
    before: str,
    after: str,
    test_args: list[str],
    witness: str,
    temp_root: Path,
) -> bool:
    with tempfile.TemporaryDirectory(prefix="rust-g1-mutant-") as directory:
        mutant = Path(directory) / "crate"
        shutil.copytree(
            ROOT,
            mutant,
            ignore=shutil.ignore_patterns("target", ".git", "output", "*.tmp"),
        )
        path = mutant / file_name
        content = path.read_text(encoding="utf-8")
        if content.count(before) != 1:
            raise RuntimeError(f"{name}: mutation anchor must occur exactly once")
        path.write_text(content.replace(before, after, 1), encoding="utf-8")
        env = dict(__import__("os").environ)
        env["CARGO_TARGET_DIR"] = str(temp_root / "target")
        result = subprocess.run(
            ["cargo", "test", "--offline", *test_args],
            cwd=mutant,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        runtime_failed = "running 1 test" in result.stdout and "test result: FAILED" in result.stdout
        detected = result.returncode != 0 and runtime_failed and witness in result.stdout
        if detected:
            print(f"DETECTED: {name} (compiled; runtime witness: {witness})")
        elif result.returncode == 0:
            print(f"MISSED: {name}")
        else:
            print(f"INVALID: {name} failed without expected witness {witness!r}")
        if not detected:
            print(result.stdout[-4000:])
        return detected


def main() -> int:
    baseline = subprocess.run(
        ["cargo", "test", "--offline", "--test", "single_contract"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if baseline.returncode != 0:
        print("Baseline offline tests must pass before mutation checks.")
        print(baseline.stdout[-4000:])
        return 2
    with tempfile.TemporaryDirectory(prefix="rust-g1-mutation-gate-") as directory:
        root = Path(directory)
        results = [run_mutation(*mutation, root) for mutation in MUTATIONS]
    print(f"Mutation witnesses: {sum(results)}/{len(results)}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
