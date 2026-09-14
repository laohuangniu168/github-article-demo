from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import re

from local_only_safety import assert_digest_output_path


FINAL_LOCAL_STATE = 'PENDING_MANUAL_REVIEW'
_LINK = re.compile(r'\[([^\]\r\n]+)\]\((https?://[^\s<>\r\n()]+)\)')


@dataclass(frozen=True)
class LocalDigestPreviewResult:
    status: str
    markdown_path: Path
    html_path: Path
    evidence_path: Path
    clickable_href_count: int
    state_history: tuple[str, ...]


def _inline_html(text: str) -> tuple[str, int]:
    parts: list[str] = []
    offset = 0
    count = 0
    for match in _LINK.finditer(text):
        parts.append(escape(text[offset:match.start()]))
        parts.append('<a href="' + escape(match.group(2), quote=True) + '">' + escape(match.group(1)) + '</a>')
        offset = match.end()
        count += 1
    parts.append(escape(text[offset:]))
    return ''.join(parts), count


def render_static_html(markdown: str) -> tuple[str, int]:
    if not isinstance(markdown, str):
        raise TypeError('markdown must be str')
    body: list[str] = []
    href_count = 0
    for line in markdown.splitlines():
        if not line:
            continue
        content, found = _inline_html(line.lstrip('#- ').strip())
        href_count += found
        if line.startswith('### '):
            body.append('<h3>' + content + '</h3>')
        elif line.startswith('## '):
            body.append('<h2>' + content + '</h2>')
        elif line.startswith('# '):
            body.append('<h1>' + content + '</h1>')
        elif line.startswith('- '):
            body.append('<p>' + content + '</p>')
        else:
            body.append('<p>' + content + '</p>')
    document = '<!doctype html>\n<html><head><meta charset="utf-8"><title>Digest Preview</title></head><body>\n'
    document += '\n'.join(body) + '\n</body></html>\n'
    return document, href_count


def create_local_digest_preview(
    *, project_root: Path | str, filename: str, markdown: str, audit_status: str,
) -> LocalDigestPreviewResult:
    name = Path(filename)
    if name.name != filename or name.suffix.casefold() != '.md':
        raise ValueError('filename must be a Markdown basename')
    if audit_status != 'PASS':
        raise ValueError('audit must pass before preview')
    root = Path(project_root).resolve()
    markdown_path = assert_digest_output_path(root, Path('output/digest/markdown') / name)
    html_path = assert_digest_output_path(root, Path('output/digest/html') / (name.stem + '.html'))
    evidence_path = assert_digest_output_path(root, Path('output/digest/evidence') / (name.stem + '.json'))
    html, href_count = render_static_html(markdown)
    for parent in (markdown_path.parent, html_path.parent, evidence_path.parent):
        parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding='utf-8', newline='')
    html_path.write_text(html, encoding='utf-8', newline='')
    evidence = {
        'audit_status': audit_status,
        'clickable_href_count': href_count,
        'final_state': FINAL_LOCAL_STATE,
        'publication_mode': 'LOCAL_ONLY',
        'state_history': ['GENERATED', 'AUDITED', 'PREVIEW_READY', FINAL_LOCAL_STATE],
    }
    evidence_path.write_text(json.dumps(evidence, sort_keys=True, indent=2) + '\n', encoding='utf-8', newline='')
    return LocalDigestPreviewResult(
        status=FINAL_LOCAL_STATE,
        markdown_path=markdown_path,
        html_path=html_path,
        evidence_path=evidence_path,
        clickable_href_count=href_count,
        state_history=('GENERATED', 'AUDITED', 'PREVIEW_READY', FINAL_LOCAL_STATE),
    )
