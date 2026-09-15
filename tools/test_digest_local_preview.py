from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from digest_local_preview import create_local_digest_preview, render_static_html


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(value for name, value in attrs if name == 'href')


class DigestLocalPreviewTests(unittest.TestCase):
    def test_digest_metadata_hidden_and_twenty_entries_preserved(self):
        urls = [
            f'{"http" if index % 2 else "https"}://example.org/News//Item%2F{index}?q=One&lang=zh#Part'
            for index in range(20)
        ]
        summary = '围绕标题提供主题导读，关注日常生活中的观察与思考。'
        markdown = ('---\ntitle: "Metadata title"\ndescription: "Metadata description"\n---\n'
                    '\n# Digest\n\n{% raw %}\n\n## 主题分类\n\n')
        markdown += '\n'.join(
            f'### 新闻标题 {index}\n\n{summary}\n\n| 详见 [新闻标题 {index}]({url})\n'
            for index, url in enumerate(urls)
        ) + '\n{% endraw %}\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'output/digest/markdown/synthetic.md'
            source.parent.mkdir(parents=True)
            original = markdown.replace('\n', '\r\n').encode('utf-8')
            source.write_bytes(original)
            original_mtime = source.stat().st_mtime_ns
            result = create_local_digest_preview(
                project_root=root, filename=source.name,
                markdown=source.read_text(encoding='utf-8'), audit_status='PASS',
            )
            html = result.html_path.read_text(encoding='utf-8')
            for hidden in ('title:', 'description:', 'Metadata title', 'Metadata description',
                           '---', '{% raw %}', '{% endraw %}'):
                with self.subTest(hidden=hidden):
                    self.assertNotIn(hidden, html)
            self.assertIn('<h1>Digest</h1>', html)
            self.assertIn('<h2>主题分类</h2>', html)
            for index in range(20):
                self.assertIn(f'<h3>新闻标题 {index}</h3>', html)
            self.assertEqual(20, html.count(summary))
            links = LinkCollector()
            links.feed(html)
            self.assertEqual(urls, links.hrefs)
            self.assertEqual(20, result.clickable_href_count)
            self.assertEqual(original, source.read_bytes())
            self.assertEqual(original_mtime, source.stat().st_mtime_ns)

    def test_front_matter_with_bom_crlf_and_yaml_end_marker(self):
        for end in ('---', '...'):
            with self.subTest(end=end):
                html, _ = render_static_html(
                    '\ufeff---\r\ntitle: hidden\r\n' + end + '\r\n# Visible\r\n'
                )
                self.assertNotIn('title: hidden', html)
                self.assertIn('<h1>Visible</h1>', html)

    def test_nonleading_or_unclosed_metadata_is_not_discarded(self):
        for markdown in ('# Heading\n---\ntitle: body text\n---\n',
                         '---\ntitle: body text\n# Heading\n'):
            with self.subTest(markdown=markdown):
                html, _ = render_static_html(markdown)
                self.assertIn('title: body text', html)
                self.assertIn('<h1>Heading</h1>', html)

    def test_standalone_liquid_tags_do_not_remove_enclosed_body(self):
        html, _ = render_static_html('# Heading\n  {% raw %}  \nBody\n\t{% endraw %}\nAfter\n')
        self.assertNotIn('{% raw %}', html)
        self.assertNotIn('{% endraw %}', html)
        self.assertIn('<p>Body</p>', html)
        self.assertIn('<p>After</p>', html)

    def test_existing_markdown_mismatch_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'output/digest/markdown/synthetic.md'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'# Original\r\n')
            with self.assertRaises(ValueError):
                create_local_digest_preview(project_root=root, filename=source.name,
                    markdown='# Different\n', audit_status='PASS')
            self.assertEqual(b'# Original\r\n', source.read_bytes())
            self.assertFalse((root / 'output/digest/html').exists())

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
