#!/usr/bin/env python3
"""Run fail-closed source mutations against focused offline witnesses."""

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
    (
        "key-level credential redaction removed or narrowed",
        "src/sanitize.rs",
        '    "secret",\n    "cookie",',
        '    "secrettail",\n    "cookie",',
        ["--lib", "output::tests::persisted_common_credential_keys_are_removed_at_output_boundaries"],
        "secret persisted",
    ),
    (
        "extended text credential redaction narrowed",
        "src/sanitize.rs",
        '            "credentials",\n            "client_credentials",',
        '            "credentialtail",\n            "client_credentials",',
        ["--lib", "output::tests::persisted_extended_text_credentials_are_redacted_across_output_surfaces"],
        "secret persisted",
    ),
    (
        "extended JSON key suffix redaction narrowed",
        "src/sanitize.rs",
        '    "credentials",\n    "privatekey",',
        '    "credentialtail",\n    "privatekey",',
        ["--lib", "output::tests::extended_credential_keys_removed_and_business_flags_preserved_on_disk"],
        "secret persisted",
    ),
    (
        "explicit benign business-key exception removed",
        "src/sanitize.rs",
        '    "usecookie",',
        '    "usecookie_disabled",',
        ["--lib", "sanitize::tests::extended_sensitive_key_suffixes_and_benign_flags_are_distinguished"],
        "business key over-redacted",
    ),
    (
        "private-key text assignment redaction narrowed",
        "src/sanitize.rs",
        '            "privatekey",',
        '            "privatekey_disabled",',
        ["--lib", "output::tests::persisted_secret_and_private_key_assignments_are_redacted_across_surfaces"],
        "secret persisted",
    ),
    (
        "Bearer placeholder idempotence removed",
        "src/sanitize.rs",
        """            if let Some(end) = redacted_value_end(&chars, value_start) {
                out.extend(chars[i..end].iter());
                i = end;
                continue;
            }
""",
        "            if false { continue; }\n",
        [
            "--lib",
            "sanitize::tests::bearer_and_composed_redaction_are_idempotent_for_selected_and_generated_inputs",
        ],
        "redaction must be idempotent",
    ),
    (
        "native bulk sends duplicate typed identities",
        "src/bulk.rs",
        "let actor_urls = tasks\n        .iter()\n        .map(|task| task.source_urls[0].clone())\n        .collect();",
        "let actor_urls = urls.to_vec();",
        ["--lib", "bulk::tests::native_bulk_executes_one_post_with_unique_typed_inputs_and_journals_first"],
        "Actor receives unique identities once",
    ),
    (
        "typed attribution ignores media type",
        "src/bulk.rs",
        ".filter(|(_, t)| t.identity.media_type == media && t.identity.shortcode == code)",
        ".filter(|(_, t)| true && t.identity.shortcode == code)",
        ["--lib", "bulk::tests::typed_fallback_does_not_cross_media_types_with_same_shortcode"],
        "typed fallback crossed media types",
    ),
    (
        "unknown batch is incorrectly promoted to success",
        "src/bulk.rs",
        "return BatchStatus::Unknown;",
        "return BatchStatus::Success;",
        ["--lib", "bulk::tests::frozen_dataset_fixtures_01_through_06_are_deterministic"],
        "all shortcode-only ambiguity remains unknown",
    ),
    (
        "creation unknown retries bulk POST",
        "src/bulk.rs",
        "Err(e) => {\n            let code = if e.kind == ErrorKind::CreateRejected {",
        "Err(e) => {\n            let _retry_probe = post_run(config, &input);\n            let code = if e.kind == ErrorKind::CreateRejected {",
        ["--lib", "bulk::tests::uncertain_bulk_create_is_not_retried_and_has_no_task_rows"],
        "creation_unknown must not retry create POST",
    ),
    (
        "bulk public result skips RawItem text sanitization",
        "src/bulk.rs",
        "pending[task].push((0, sanitize_value(item), attr))",
        "pending[task].push((0, item.clone(), attr))",
        ["--lib", "bulk::tests::normal_bulk_serialization_uses_frozen_camel_case_schema_and_counts"],
        "secret persisted",
    ),
    (
        "Reel/Reels typed URL alias attribution disabled",
        "src/bulk.rs",
        """        if let [index] = typed_matches.as_slice() {
            return Evidence::Assigned(*index, Attribution::TypedFallback);
        }
""",
        """        if false {
            return Evidence::Assigned(typed_matches[0], Attribution::TypedFallback);
        }
""",
        ["--lib", "bulk::tests::reel_alias_urls_match_by_typed_identity_in_both_directions"],
        "left: Empty",
    ),
    (
        "duplicate mixed evidence priority changed",
        "src/bulk.rs",
        """    if candidates
        .iter()
        .any(|(_, _, attribution)| *attribution == Attribution::ExactUrl)
""",
        """    if false
""",
        ["--lib", "bulk::tests::mixed_duplicate_evidence_prefers_exact_url_attribution"],
        "left: TypedFallback",
    ),
    (
        "Native Bulk URL typed identity ignores media type",
        "src/bulk.rs",
        "task.identity.media_type == media && task.identity.shortcode == code",
        "task.identity.shortcode == code",
        [
            "--lib",
            "bulk::tests::execute_bulk_url_identity_never_crosses_post_and_reel_media_types",
        ],
        "left: Success",
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
