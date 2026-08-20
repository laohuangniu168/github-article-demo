from __future__ import annotations

import argparse
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = (
    "https://laohuangniu168.github.io/"
    "github-article-demo/articles/"
)


def resolve_input_file(path: Path) -> Path:
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def validate_base_url(base_url: str) -> str:
    if "[" in base_url or "](" in base_url:
        raise ValueError("base URL 不接受 Markdown 链接格式")

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL 必须是有效的 HTTP/HTTPS URL")

    return base_url.rstrip("/") + "/"


def load_slugs(input_file: Path) -> list[str]:
    if not input_file.exists():
        raise FileNotFoundError(f"输入文件不存在：{input_file}")

    slugs: list[str] = []

    for line_number, raw_line in enumerate(
        input_file.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue

        if "[" in line or "](" in line:
            raise ValueError(
                f"第 {line_number} 行不接受 Markdown 链接格式"
            )

        slug = line.split("|", 1)[0].strip()
        if not slug or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
            for character in slug
        ):
            raise ValueError(f"第 {line_number} 行 slug 非法：{slug}")

        slugs.append(slug)

    if not slugs:
        raise ValueError("输入文件中没有有效 slug")

    return slugs


def request_status(url: str, timeout: float) -> int | None:
    request = Request(
        url,
        method="HEAD",
        headers={"User-Agent": "github-article-demo-url-verifier/1.0"},
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError, OSError):
        return None


def verify_urls(
    slugs: list[str],
    base_url: str,
    timeout: float,
) -> tuple[int, int]:
    passed = 0
    failed = 0

    for slug in slugs:
        url = f"{base_url}{slug}.html"
        status = request_status(url, timeout)

        if status == 200:
            passed += 1
            print(f"HTTP 200 | {slug}")
        else:
            failed += 1
            label = str(status) if status is not None else "ERROR"
            print(f"HTTP {label} | {slug}")

    return passed, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify published GitHub Pages article URLs"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")

    try:
        input_file = resolve_input_file(args.input)
        base_url = validate_base_url(args.base_url)
        slugs = load_slugs(input_file)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        return 2

    passed, failed = verify_urls(slugs, base_url, args.timeout)

    print()
    print(f"HTTP 200：{passed}")
    print(f"FAIL：{failed}")
    print(f"TOTAL：{len(slugs)}")

    if failed:
        print("FINAL: FAIL")
        return 1

    print("FINAL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
