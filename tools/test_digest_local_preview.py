from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from digest_local_preview import create_local_digest_preview


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(value for name, value in attrs if name == 'href')


class DigestLocalPreviewTests(unittest.TestCase):
    def test_static_preview_preserves_links_and_requires_manual_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            urls = [
                'http://example.test/a',
                'https://example.test/b',
                'https://example.test/path//item',
                'https://example.test/search?q=one&lang=zh',
                'https://example.test/page#part',
            ]
            urls = [urls[index % len(urls)] + ('&n=' + str(index) if '?' in urls[index % len(urls)] else '?n=' + str(index)) for index in range(20)]
            markdown = '# Synthetic Digest\n\n' + '\n'.join(
                f'- [Synthetic {index + 1}]({url})' for index, url in enumerate(urls)
            ) + '\n'
            result = create_local_digest_preview(
                project_root=root, filename='synthetic.md', markdown=markdown,
                audit_status='PASS',
            )
            parser = LinkCollector()
            parser.feed(result.html_path.read_text(encoding='utf-8'))
            self.assertEqual(urls, parser.hrefs)
            self.assertEqual(markdown, result.markdown_path.read_text(encoding='utf-8'))
            self.assertEqual('PENDING_MANUAL_REVIEW', result.status)
            self.assertEqual(
                ('GENERATED', 'AUDITED', 'PREVIEW_READY', 'PENDING_MANUAL_REVIEW'),
                result.state_history,
            )
            self.assertEqual(20, result.clickable_href_count)
            self.assertFalse(hasattr(result, 'published_url'))

    def test_failed_audit_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                create_local_digest_preview(
                    project_root=root, filename='synthetic.md', markdown='# Draft\n',
                    audit_status='FAIL',
                )
            self.assertFalse((root / 'output').exists())

    def test_module_has_no_network_openai_or_publish_dependency(self):
        source = Path(__file__).with_name('digest_local_preview.py').read_text(encoding='utf-8').casefold()
        for token in ('requests', 'urllib', 'socket', 'httpx', 'openai', 'publish_articles', 'verify_public_urls'):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == '__main__':
    unittest.main()
