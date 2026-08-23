from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

from internal_link_registry import (
    CANONICAL_BASE,
    REGISTRY_SCHEMA_VERSION,
    SOURCE_BATCHES,
    RegistryError,
    build_registry,
    compute_article_hashes,
    compute_registry_version,
    validate_registry,
    verify_article_hashes,
)


class RegistryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "input").mkdir()
        (root / "articles").mkdir()
        self.specs = []
        for index, batch in enumerate(SOURCE_BATCHES, start=1):
            slug = f"technical-seo-fixture-{index}"
            title = f"测试标题{index}"
            self.specs.append((batch, slug, title))
            (root / "input" / batch).write_text(f"{slug}|{title}\n", encoding="utf-8")
            self.write_article(slug, title)

    def write_article(self, slug: str, title: str) -> None:
        (self.root / "articles" / f"{slug}.md").write_text(
            f'---\ntitle: "{title}"\ndescription: "测试描述"\n---\n\n# {title}\n',
            encoding="utf-8",
        )

    def build(self):
        return build_registry(self.root, expected_batch_counts=(1, 1, 1, 1))


class InternalLinkRegistryTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return RegistryFixture(Path(temporary.name))

    def assert_registry_code(self, code: str, callback) -> None:
        with self.assertRaises(RegistryError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_exact_source_batch_list(self) -> None:
        fixture = self.fixture()
        wrong = SOURCE_BATCHES[:-1]
        self.assert_registry_code(
            "SOURCE_BATCH_MISMATCH",
            lambda: build_registry(fixture.root, source_batches=wrong, expected_batch_counts=(1, 1, 1)),
        )

    def test_real_registry_exact_total_180(self) -> None:
        snapshot = build_registry(PROJECT_ROOT)
        self.assertEqual(len(snapshot.entries), 180)

    def test_duplicate_protection(self) -> None:
        fixture = self.fixture()
        _, slug, title = fixture.specs[0]
        second_batch = fixture.root / "input" / SOURCE_BATCHES[1]
        second_batch.write_text(f"{slug}|{title}二\n", encoding="utf-8")
        self.assert_registry_code("DUPLICATE_SLUG", fixture.build)

    def test_missing_article_file(self) -> None:
        fixture = self.fixture()
        _, slug, _ = fixture.specs[0]
        (fixture.root / "articles" / f"{slug}.md").unlink()
        self.assert_registry_code("REGISTRY_TARGET_MISSING", fixture.build)

    def test_title_mismatch(self) -> None:
        fixture = self.fixture()
        _, slug, _ = fixture.specs[0]
        fixture.write_article(slug, "不同标题")
        self.assert_registry_code("TITLE_MISMATCH", fixture.build)

    def test_canonical_url(self) -> None:
        entry = self.fixture().build().entries[0]
        self.assertEqual(entry.canonical_url, f"{CANONICAL_BASE}{entry.slug}.html")

    def test_relative_url(self) -> None:
        entry = self.fixture().build().entries[0]
        self.assertEqual(entry.relative_url, f"./{entry.slug}.html")

    def test_published_and_eligible_flags(self) -> None:
        snapshot = self.fixture().build()
        self.assertTrue(all(entry.published and entry.eligible_as_target for entry in snapshot.entries))

    def test_extra_nonproduction_article_excluded(self) -> None:
        fixture = self.fixture()
        fixture.write_article("extra-article", "额外文章")
        slugs = {entry.slug for entry in fixture.build().entries}
        self.assertNotIn("extra-article", slugs)

    def test_deterministic_registry_version(self) -> None:
        fixture = self.fixture()
        self.assertEqual(fixture.build().registry_version, fixture.build().registry_version)

    def test_changed_payload_changes_registry_version(self) -> None:
        snapshot = self.fixture().build()
        changed = (replace(snapshot.entries[0], title="变化"), *snapshot.entries[1:])
        self.assertNotEqual(
            snapshot.registry_version,
            compute_registry_version(changed, source_batches=snapshot.source_batches),
        )

    def test_schema_mismatch(self) -> None:
        snapshot = self.fixture().build()
        changed = replace(snapshot, registry_schema_version="2")
        self.assert_registry_code(
            "REGISTRY_SCHEMA_MISMATCH",
            lambda: validate_registry(changed, expected_schema_version=REGISTRY_SCHEMA_VERSION),
        )

    def test_source_batch_mismatch(self) -> None:
        snapshot = self.fixture().build()
        changed = replace(snapshot, source_batches=("other.txt",))
        self.assert_registry_code("SOURCE_BATCH_MISMATCH", lambda: validate_registry(changed))

    def test_existing_article_hashes_unchanged(self) -> None:
        fixture = self.fixture()
        snapshot = fixture.build()
        baseline = compute_article_hashes(snapshot, fixture.root)
        verify_article_hashes(baseline, snapshot, fixture.root)


if __name__ == "__main__":
    unittest.main()
