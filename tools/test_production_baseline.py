import hashlib
from pathlib import Path
import random
import unittest
from unittest.mock import patch

import production_baseline as baseline


class ProductionBaselineTests(unittest.TestCase):
    def setUp(self):
        self.contents = {}
        index = 0
        for name, count in baseline.PRODUCTION_BATCHES:
            lines = []
            for _ in range(count):
                slug = f"production-{index:03d}"
                lines.append(f"{slug}|Controlled title")
                self.contents[f"articles/{slug}.md"] = b"# Title\n\nBody\n"
                index += 1
            self.contents["input/" + name] = ("\n".join(lines) + "\n").encode()
        self.reader = patch.object(baseline, "_repository_bytes", side_effect=self.read)
        self.reader.start()
        self.addCleanup(self.reader.stop)
        resolve = patch.object(baseline, "_resolve_commit", return_value="a" * 40)
        resolve.start()
        self.addCleanup(resolve.stop)

    def read(self, root, commit, path):
        return self.contents[path]

    def test_exact_200_and_repository_bytes(self):
        manifest = baseline.build_production_baseline_manifest(Path("root"))
        self.assertEqual(200, len(manifest))
        self.assertEqual(200, len({row["relative_path"] for row in manifest}))
        self.assertEqual(hashlib.sha256(b"# Title\n\nBody\n").hexdigest(),
                         manifest[0]["repository_content_sha256"])

    def test_canonical_bytes_exact_format(self):
        rows = [{"repository_content_sha256": "a" * 64, "relative_path": "articles/a.md"}]
        expected = ('[{"relative_path":"articles/a.md","repository_content_sha256":"'
                    + "a" * 64 + '"}]').encode()
        self.assertEqual(expected, baseline.canonical_manifest_bytes(rows))
        self.assertEqual(hashlib.sha256(expected).hexdigest(), baseline.compute_production_aggregate(rows))

    def test_order_independence(self):
        rows = baseline.build_production_baseline_manifest("root")
        expected = baseline.compute_production_aggregate(rows)
        random.Random(42).shuffle(rows)
        self.assertEqual(expected, baseline.compute_production_aggregate(rows))

    def test_crlf_worktree_independence(self):
        results = []
        for materialized in (b"# Title\n\nBody\n", b"# Title\r\n\r\nBody\r\n"):
            with patch.object(Path, "read_bytes", return_value=materialized) as worktree:
                results.append(baseline.compute_production_aggregate(
                    baseline.build_production_baseline_manifest("root")))
                worktree.assert_not_called()
        self.assertEqual(results[0], results[1])

    def test_workspace_root_independence(self):
        manifests = [baseline.build_production_baseline_manifest(root)
                     for root in ("C:/first/repository", "/different/repository")]
        self.assertEqual(manifests[0], manifests[1])

    def test_does_not_normalize_repository_content_or_bom(self):
        path = "articles/production-000.md"
        self.contents[path] = b"\xef\xbb\xbf# Title\r\n"
        row = baseline.build_production_baseline_manifest("root")[0]
        self.assertEqual(hashlib.sha256(self.contents[path]).hexdigest(), row["repository_content_sha256"])

    def test_file_set_is_selected_only_from_release(self):
        calls = []
        def read(root, commit, path):
            calls.append((commit, path))
            return self.contents[path]
        with patch.object(baseline, "_repository_bytes", side_effect=read):
            baseline.build_production_baseline_manifest("root")
        self.assertTrue(all(commit == baseline.RELEASE_COMMIT for commit, path in calls
                            if path.startswith("input/")))

    def test_duplicate_selection_rejected(self):
        name = "input/" + baseline.PRODUCTION_BATCHES[0][0]
        self.contents[name] = self.contents[name].replace(b"production-001", b"production-000")
        with self.assertRaises(baseline.ProductionBaselineError):
            baseline.build_production_baseline_manifest("root")

    def test_missing_selection_rejected(self):
        name = "input/" + baseline.PRODUCTION_BATCHES[0][0]
        self.contents[name] = b""
        with self.assertRaises(baseline.ProductionBaselineError):
            baseline.build_production_baseline_manifest("root")

    def test_historical_three_field_batches_supported(self):
        name = "input/" + baseline.PRODUCTION_BATCHES[-1][0]
        self.contents[name] = self.contents[name].replace(b"Controlled title", b"Controlled title|baidu-crawl")
        self.assertEqual(200, len(baseline.build_production_baseline_manifest("root")))

    def test_manifest_invalid_fields_hash_path_duplicate_rejected(self):
        good = {"relative_path": "articles/a.md", "repository_content_sha256": "a" * 64}
        cases = [[good, good], [dict(good, extra="ignored?")],
                 [dict(good, repository_content_sha256="bad")],
                 [dict(good, relative_path="../outside.md")], []]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(baseline.ProductionBaselineError):
                baseline.compute_production_aggregate(rows)

    def test_verify_pass_and_manifest_tampering_rejected(self):
        manifest = baseline.build_production_baseline_manifest("root")
        result = baseline.verify_production_baseline("root", manifest)
        self.assertEqual("PASS", result["status"])
        for changed in (manifest[:-1], [dict(manifest[0], repository_content_sha256="0" * 64), *manifest[1:]],
                        [dict(manifest[0], relative_path="articles/unknown.md"), *manifest[1:]]):
            with self.subTest(changed=changed[0]), self.assertRaises(baseline.ProductionBaselineError):
                baseline.verify_production_baseline("root", changed)

    def test_committed_content_drift_rejected(self):
        def read(root, commit, path):
            data = self.contents[path]
            return data + b"drift" if commit != baseline.RELEASE_COMMIT and path.endswith(".md") else data
        with patch.object(baseline, "_repository_bytes", side_effect=read):
            with self.assertRaisesRegex(baseline.ProductionBaselineError, "CONTENT_DRIFT"):
                baseline.verify_production_baseline("root")

    def test_git_failure_fails_closed_and_disables_lazy_fetch(self):
        import subprocess
        with patch.object(baseline.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "git")) as run:
            with self.assertRaises(baseline.ProductionBaselineError):
                baseline._git("root", "show", "missing")
        self.assertEqual("1", run.call_args.kwargs["env"]["GIT_NO_LAZY_FETCH"])


if __name__ == "__main__":
    unittest.main()
