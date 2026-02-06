#!/usr/bin/env python3
"""Fetch Google Fonts CSS and self-host the referenced font binaries.

Writes:
- assets/css/fonts.css
Downloads:
- assets/fonts/*.woff2

This keeps the site fully local/offline while preserving original typography.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT_DIR / "assets"
CSS_DIR = ASSETS_DIR / "css"
FONTS_DIR = ASSETS_DIR / "fonts"

DEFAULT_FAMILIES = [
    "PT Sans:ital,wght@0,400;0,700;1,400",
    "Raleway:wght@400;700",
]


def _http_get_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            # Use a modern browser UA so Google serves woff2 where available.
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "text/css,*/*;q=0.1",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def build_google_fonts_css_url(families: list[str], display: str) -> str:
    # https://fonts.googleapis.com/css2?family=...
    query_parts: list[tuple[str, str]] = [("family", fam) for fam in families]
    query_parts.append(("display", display))
    return "https://fonts.googleapis.com/css2?" + urlencode(query_parts)


_FONT_URL_RE = re.compile(r"url\((['\"]?)(https://fonts\.gstatic\.com/[^'\")]+)\1\)")


def rewrite_and_download(css_text: str) -> tuple[str, int]:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    for _, font_url in sorted(set(_FONT_URL_RE.findall(css_text))):
        font_name = Path(urlparse(font_url).path).name
        if not font_name:
            continue

        if not any(font_name.endswith(ext) for ext in (".woff2", ".woff", ".ttf", ".otf")):
            continue

        local_font_path = FONTS_DIR / font_name
        if not local_font_path.exists():
            data = _http_get_bytes(font_url)
            local_font_path.write_bytes(data)
            downloaded += 1

        css_text = css_text.replace(font_url, f"../fonts/{font_name}")

    return css_text, downloaded


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Self-host Google Fonts into assets/")
    parser.add_argument(
        "--family",
        action="append",
        dest="families",
        help="Google Fonts css2 family string; can be repeated",
    )
    parser.add_argument("--display", default="swap")
    parser.add_argument(
        "--out",
        default=str(CSS_DIR / "fonts.css"),
        help="Output CSS path (default: assets/css/fonts.css)",
    )

    args = parser.parse_args(argv)

    families = args.families or DEFAULT_FAMILIES
    url = build_google_fonts_css_url(families=families, display=args.display)

    CSS_DIR.mkdir(parents=True, exist_ok=True)

    css_remote = _http_get_text(url)
    css_local, downloaded = rewrite_and_download(css_remote)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "/* Self-hosted Google Fonts (generated). */\n" + css_local,
        encoding="utf-8",
    )

    print(f"Wrote {out_path.relative_to(ROOT_DIR)}")
    print(f"Downloaded {downloaded} new .woff2 files into assets/fonts/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
