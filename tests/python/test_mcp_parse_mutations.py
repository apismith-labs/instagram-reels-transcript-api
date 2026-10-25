"""Negative controls run only against disposable copies of the shared parser."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/mcp_parse.py"
FIXTURE_PATH = ROOT / "tests/fixtures/dx2-native-mcp-record.redacted.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())


def load_isolated(source_text, directory, name):
    path = Path(directory) / f"{name}.py"
    path.write_text(source_text)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MutationSensitivityTests(unittest.TestCase):
    def mutant(self, name, transform):
        original = SOURCE.read_text()
        changed = transform(original)
        self.assertNotEqual(changed, original, f"{name} mutation did not apply")
        td = tempfile.TemporaryDirectory(prefix="dx2-mcp-parser-mutant-")
        self.addCleanup(td.cleanup)
        return load_isolated(changed, td.name, name)

    def test_rollback_fix1r_makes_t01_fail(self):
        def remove_url_identity(source):
            return source.replace('PAGE_URL_KEYS = ("url",)', 'PAGE_URL_KEYS = ("videoUrl",)', 1)
        mutant = self.mutant("mutant_fix1", remove_url_identity)
        payload = FIXTURE["dataset"]["structuredContent"]
        result = mutant.classify(payload["items"], FIXTURE["expectedShortcodes"])
        self.assertNotEqual(result["verdict"], "PASS")

    def test_rollback_fix3r_makes_t09_fail(self):
        def remove_run_path_resolution(source):
            target = 'path_candidates.append((OBSERVED_DATASET_PATH, direct_value.strip()))'
            source = source.replace(target, 'pass  # FIX-3R mutation: canonical path disabled', 1)
            target = 'path_candidates.append((f"content[{i}].text.{OBSERVED_DATASET_PATH}", content_value.strip()))'
            return source.replace(target, 'pass  # FIX-3R mutation: content path disabled', 1)
        mutant = self.mutant("mutant_fix3", remove_run_path_resolution)
        with self.assertRaises(mutant.MCPParseError) as caught:
            mutant.run_metadata(FIXTURE["run"], expected_run_id="JyaFWeQ1SrLXIteIK")
        self.assertEqual(caught.exception.code, "DATASET_ID_UNAVAILABLE")

    def test_rollback_fix4r_makes_t17_fail(self):
        def restore_build_gate(source):
            target = '    result = classify(page.items, expected_shortcodes)\n'
            replacement = (target + '    if run.build_verified != "VERIFIED":\n'
                           '        result["verdict"] = "PARTIAL"  # FIX-4R mutation\n')
            return source.replace(target, replacement, 1)
        mutant = self.mutant("mutant_fix4", restore_build_gate)
        run = mutant.run_metadata(FIXTURE["run"], expected_run_id="JyaFWeQ1SrLXIteIK")
        page = mutant.dataset_items(FIXTURE["dataset"], expected_dataset_id="MHT7DmSNRX0kmcsKg")
        self.assertNotEqual(mutant.acceptance(run, page, FIXTURE["expectedShortcodes"])["verdict"], "PASS")

    def test_rollback_fix5r_makes_t11_t12_fail(self):
        def prefer_content_blocks(source):
            target = '    candidates: list[tuple[str, Any]] = []\n'
            replacement = (target + '    if isinstance(payload.get("content"), list):\n'
                           '        candidates.append(("content", payload["content"]))\n')
            source = source.replace(target, replacement, 1)
            reject = '    if all(set(item).issubset({"type", "text"}) and "type" in item for item in value):\n        return None\n'
            return source.replace(reject, '    if False:  # FIX-5R mutation: accept text blocks\n        return None\n', 1)
        mutant = self.mutant("mutant_fix5", prefer_content_blocks)
        page = mutant.dataset_items(FIXTURE["dataset"], expected_dataset_id="MHT7DmSNRX0kmcsKg")
        self.assertEqual(page.items_source, "content")
        self.assertIn("type", page.items[0])
        self.assertNotIn("url", page.items[0])

    def test_dataset_echo_guard_mutation_is_detected(self):
        target = '''    if expected_dataset_id and dataset_id != expected_dataset_id:\n        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Dataset ID echo did not match the Run")\n'''
        changed = SOURCE.read_text().replace(target, "    if False:  # mutation: Dataset echo guard removed\n        raise MCPParseError(\"DATASET_RUN_BINDING_MISMATCH\", \"Dataset ID echo did not match the Run\")\n", 1)
        mutant = self.mutant("mutant_dataset_echo", lambda _source: changed)
        with self.assertRaises(AssertionError):
            with self.assertRaises(mutant.MCPParseError):
                mutant.dataset_items(FIXTURE["dataset"], expected_dataset_id="WRONG_DATASET")

    def test_run_identity_guard_mutation_is_detected(self):
        target = '''    if expected_run_id is not None and run_id != expected_run_id:\n        raise MCPParseError("RUN_IDENTITY_MISMATCH", "Run ID did not match the expected Run")\n'''
        changed = SOURCE.read_text().replace(target, "    if False:  # mutation: Run identity comparison removed\n        raise MCPParseError(\"RUN_IDENTITY_MISMATCH\", \"Run ID did not match the expected Run\")\n", 1)
        mutant = self.mutant("mutant_run_identity", lambda _source: changed)
        with self.assertRaises(AssertionError):
            self.assertEqual(mutant.extract_run_identity({"runId": "OTHER_RUN_12345678"},
                                                         expected_run_id="JyaFWeQ1SrLXIteIK"),
                             "JyaFWeQ1SrLXIteIK")

    def test_rest_fallback_flag_bypass_mutation_is_detected(self):
        target = '            if key in ("keyValueStores", "restFallback"):\n                continue\n'
        changed = SOURCE.read_text().replace(target,
            '            if key == "keyValueStores":  # mutation: restFallback exclusion removed\n                continue\n', 1)
        mutant = self.mutant("mutant_rest_fallback_gate", lambda _source: changed)
        payload = {"structuredContent": {"runId": "JyaFWeQ1SrLXIteIK", "status": "SUCCEEDED"},
                   "restFallback": {"defaultDatasetId": "MHT7DmSNRX0kmcsKg"}}
        with self.assertRaises(AssertionError):
            with self.assertRaises(mutant.MCPParseError) as caught:
                mutant.run_metadata(payload, expected_run_id="JyaFWeQ1SrLXIteIK",
                                    allow_rest_fallback=False)
            self.assertEqual(caught.exception.code, "DATASET_ID_UNAVAILABLE")

    def test_build_comparison_mutation_is_detected(self):
        target = '''    if ((expects_number and has_number and build_number != expected_build_number)\n            or (expects_id and has_id and build_id != expected_build_id)):\n        return "BUILD_DRIFT"\n'''
        changed = SOURCE.read_text().replace(target,
            '''    if False and ((expects_number and has_number and build_number != expected_build_number)\n            or (expects_id and has_id and build_id != expected_build_id)):\n        return "BUILD_DRIFT"\n''', 1)
        mutant = self.mutant("mutant_build_comparison", lambda _source: changed)
        payload = {"structuredContent": {"runId": "JyaFWeQ1SrLXIteIK", "status": "SUCCEEDED",
                   "buildNumber": "0.0.49", "buildId": "wrongBuildId123456"}}
        with self.assertRaises(AssertionError):
            self.assertEqual(mutant.run_metadata(payload, expected_run_id="JyaFWeQ1SrLXIteIK",
                                                  require_dataset_id=False,
                                                  expected_build_number="0.0.50",
                                                  expected_build_id=None).build_verified,
                             "BUILD_DRIFT")

    def test_dataset_identity_guard_mutation_is_detected(self):
        target = '''    if (not isinstance(run.dataset_id, str) or not run.dataset_id.strip()\n            or not isinstance(page.dataset_id, str) or not page.dataset_id.strip()):\n        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Run and Dataset identities are both required")\n'''
        changed = SOURCE.read_text().replace(target,
            '''    if False:  # mutation: missing Dataset identities accepted\n        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Run and Dataset identities are both required")\n''', 1)
        mutant = self.mutant("mutant_dataset_identity", lambda _source: changed)
        run = mutant.run_metadata({"structuredContent": {"runId": "JyaFWeQ1SrLXIteIK", "status": "SUCCEEDED"}},
                                  expected_run_id="JyaFWeQ1SrLXIteIK", require_dataset_id=False)
        payload = json.loads(json.dumps(FIXTURE["dataset"]))
        payload["structuredContent"].pop("datasetId")
        page = mutant.dataset_items(payload)
        with self.assertRaises(AssertionError):
            with self.assertRaises(mutant.MCPParseError):
                mutant.acceptance(run, page, FIXTURE["expectedShortcodes"])


if __name__ == "__main__":
    unittest.main()
