from pathlib import Path
import tempfile
import unittest

from local_only_safety import (
    LocalOnlySafetyError,
    assert_digest_output_path,
    assert_publication_candidate,
)


class LocalOnlySafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_digest_local_output_roots_are_allowed(self):
        for relative in (
            'output/digest/markdown/one.md',
            'output/digest/html/one.html',
            'output/digest/evidence/one.json',
        ):
            self.assertEqual(self.root / relative, assert_digest_output_path(self.root, relative))

    def test_new_digest_cannot_write_articles(self):
        with self.assertRaises(LocalOnlySafetyError) as caught:
            assert_digest_output_path(self.root, 'articles/new-digest.md')
        self.assertEqual('DIGEST_PRODUCTION_PATH_FORBIDDEN_IN_LOCAL_ONLY_MODE', caught.exception.code)

    def test_generated_output_cannot_be_a_publication_candidate(self):
        for action in ('stage', 'commit', 'push', 'github_pages', 'public_url_verification'):
            with self.subTest(action=action), self.assertRaises(LocalOnlySafetyError) as caught:
                assert_publication_candidate(self.root, 'output/digest/markdown/one.md', action)
            self.assertEqual('LOCAL_ONLY_PUBLICATION_VIOLATION', caught.exception.code)

    def test_source_code_git_remains_allowed(self):
        for action in ('stage', 'commit', 'push'):
            self.assertEqual(self.root / 'tools/example.py', assert_publication_candidate(
                self.root, 'tools/example.py', action,
            ))

    def test_pages_and_public_verification_are_disabled_for_local_only_workflow(self):
        for action in ('github_pages', 'public_url_verification'):
            with self.subTest(action=action), self.assertRaises(LocalOnlySafetyError) as caught:
                assert_publication_candidate(self.root, 'tools/example.py', action)
            self.assertEqual('LOCAL_ONLY_PUBLICATION_VIOLATION', caught.exception.code)

    def test_path_escape_fails_closed(self):
        with self.assertRaises(LocalOnlySafetyError) as caught:
            assert_digest_output_path(self.root, '../outside.md')
        self.assertEqual('LOCAL_ONLY_PATH_INVALID', caught.exception.code)


if __name__ == '__main__':
    unittest.main()
