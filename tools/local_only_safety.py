from __future__ import annotations

from pathlib import Path


PRODUCT_MODE = 'LOCAL_ONLY'
DIGEST_OUTPUT_ROOT = Path('output/digest')
ALLOWED_OUTPUT_AREAS = frozenset({'markdown', 'html', 'evidence'})
PUBLICATION_ACTIONS = frozenset({
    'stage', 'commit', 'push', 'github_pages', 'public_url_verification',
})


class LocalOnlySafetyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f'{code}: {message}')


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolve(project_root: Path | str, candidate: Path | str) -> tuple[Path, Path]:
    root = Path(project_root).resolve()
    value = Path(candidate)
    resolved = (root / value).resolve() if not value.is_absolute() else value.resolve()
    if not _within(resolved, root):
        raise LocalOnlySafetyError('LOCAL_ONLY_PATH_INVALID', 'path escapes project root')
    return root, resolved


def assert_digest_output_path(project_root: Path | str, candidate: Path | str) -> Path:
    root, resolved = _resolve(project_root, candidate)
    articles = (root / 'articles').resolve()
    if _within(resolved, articles):
        raise LocalOnlySafetyError(
            'DIGEST_PRODUCTION_PATH_FORBIDDEN_IN_LOCAL_ONLY_MODE',
            'new Digest output cannot be written to articles/',
        )
    output_root = (root / DIGEST_OUTPUT_ROOT).resolve()
    if not _within(resolved, output_root):
        raise LocalOnlySafetyError('LOCAL_ONLY_OUTPUT_PATH_REQUIRED', 'Digest output must use output/digest/')
    relative = resolved.relative_to(output_root)
    if len(relative.parts) < 2 or relative.parts[0] not in ALLOWED_OUTPUT_AREAS:
        raise LocalOnlySafetyError('LOCAL_ONLY_OUTPUT_PATH_REQUIRED', 'unknown Digest output area')
    return resolved


def assert_publication_candidate(
    project_root: Path | str,
    candidate: Path | str,
    action: str,
) -> Path:
    root, resolved = _resolve(project_root, candidate)
    if action not in PUBLICATION_ACTIONS:
        raise LocalOnlySafetyError('LOCAL_ONLY_ACTION_INVALID', 'unknown publication action')
    if action in {'github_pages', 'public_url_verification'} or _within(
        resolved, (root / DIGEST_OUTPUT_ROOT).resolve()
    ):
        raise LocalOnlySafetyError(
            'LOCAL_ONLY_PUBLICATION_VIOLATION',
            'generated Digest output cannot enter publication or Git delivery',
        )
    return resolved
