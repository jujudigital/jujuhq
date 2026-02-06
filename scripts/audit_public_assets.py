#!/usr/bin/env python3
"""Audit render-critical assets for the public static pages.

Scans a small, explicit set of public HTML entrypoints and any referenced CSS
files for asset dependencies (src/href/url(...)/@import), then reports:
- Missing local files required to render the pages
- Remaining external asset loads (http/https)

This intentionally ignores outbound navigation links (e.g. <a href="https://…">)
that do not load assets needed for rendering.

Usage:
  python3 scripts/audit_public_assets.py --write-broken-assets

"""

from __future__ import annotations

import argparse
import html
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit


PUBLIC_PAGES = [
    "index.html",
    "404.html",
    "contact-us/index.html",
    "irresistible/index.html",
    "privacy-policy/index.html",
]


_URL_FUNC_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_IMPORT_RE = re.compile(
    r"@import\s+(?:url\()?(?P<q>['\"])(?P<url>.*?)(?P=q)\)?\s*;",
    re.IGNORECASE,
)
_FONT_FACE_BLOCK_RE = re.compile(r"@font-face\s*\{.*?\}", re.IGNORECASE | re.DOTALL)
_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;]+);", re.IGNORECASE)


def _extract_font_families(font_family_value: str) -> set[str]:
    """Extract family names from a CSS font-family value."""

    families: set[str] = set()
    for chunk in font_family_value.split(","):
        name = chunk.strip().strip("\"'")
        if not name:
            continue
        lowered = name.lower()
        if lowered in {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}:
            continue
        families.add(name)
    return families


@dataclass(frozen=True)
class Referrer:
    source_file: str
    raw: str


def _strip_query_fragment(url: str) -> str:
    parts = urlsplit(url)
    return parts._replace(query="", fragment="").geturl()


def _is_ignored_url(url: str) -> bool:
    lowered = url.strip().lower()
    return lowered.startswith(("data:", "mailto:", "tel:", "javascript:", "#"))


def _classify_url(url: str) -> tuple[str, str] | None:
    """Return (kind, value) where kind is 'local' or 'external'.

    For local refs, value is a path-ish string (still possibly relative).
    For external refs, value is the full URL.
    """

    url = html.unescape(url.strip())
    url = url.strip("\"'")

    if not url or _is_ignored_url(url):
        return None

    if url.startswith("//"):
        return ("external", "https:" + url)

    parts = urlsplit(url)
    if parts.scheme in {"http", "https"}:
        return ("external", _strip_query_fragment(url))

    # Treat everything else as local-ish (including /absolute paths)
    return ("local", unquote(_strip_query_fragment(url)))


def _resolve_local_path(root_dir: Path, base_file: Path, raw_path: str) -> Path:
    """Resolve a local reference to an on-disk path."""

    raw_path = raw_path.strip()
    if raw_path.startswith("/"):
        return (root_dir / raw_path.lstrip("/")).resolve()

    return (base_file.parent / raw_path).resolve()


class _AssetHTMLParser(HTMLParser):
    def __init__(self, root_dir: Path, html_file: Path):
        super().__init__(convert_charrefs=True)
        self.root_dir = root_dir
        self.html_file = html_file
        self.local_refs: list[tuple[Path, str]] = []
        self.external_refs: list[str] = []
        self.used_font_families: set[str] = set()

    def _handle_url(self, url: str):
        classified = _classify_url(url)
        if classified is None:
            return

        kind, value = classified
        if kind == "external":
            self.external_refs.append(value)
            return

        resolved = _resolve_local_path(self.root_dir, self.html_file, value)
        self.local_refs.append((resolved, url))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        # Inline style attributes can pull images/fonts.
        style = attr_map.get("style")
        if style:
            for match in _FONT_FAMILY_RE.finditer(style):
                self.used_font_families |= _extract_font_families(match.group(1))
            for _, raw in _URL_FUNC_RE.findall(style):
                self._handle_url(raw)

        class_attr = attr_map.get("class")
        if class_attr and ("fa-solid" in class_attr or "fa-" in class_attr):
            # Font Awesome 6 is used via CSS classes, not inline font-family.
            self.used_font_families.add("Font Awesome 6 Free")

        if tag.lower() == "link":
            rel = (attr_map.get("rel") or "").lower()
            if any(token in rel for token in ("stylesheet", "icon", "apple-touch-icon")):
                href = attr_map.get("href")
                if href:
                    self._handle_url(href)

        if tag.lower() == "script":
            src = attr_map.get("src")
            if src:
                self._handle_url(src)

        if tag.lower() == "img":
            src = attr_map.get("src")
            if src:
                self._handle_url(src)

            srcset = attr_map.get("srcset")
            if srcset:
                for candidate in srcset.split(","):
                    candidate = candidate.strip()
                    if not candidate:
                        continue
                    candidate_url = candidate.split()[0]
                    self._handle_url(candidate_url)

        if tag.lower() in {"source", "video"}:
            for key in ("src", "poster", "srcset"):
                val = attr_map.get(key)
                if not val:
                    continue
                if key == "srcset":
                    for candidate in val.split(","):
                        candidate = candidate.strip()
                        if not candidate:
                            continue
                        candidate_url = candidate.split()[0]
                        self._handle_url(candidate_url)
                else:
                    self._handle_url(val)


def _scan_html_file(
    root_dir: Path, html_path: Path
) -> tuple[list[tuple[Path, str]], list[str], set[str]]:
    text = html_path.read_text(encoding="utf-8", errors="replace")

    parser = _AssetHTMLParser(root_dir, html_path)
    parser.feed(text)

    # Also scan the entire HTML for url(...) patterns (e.g. in <style> blocks).
    for _, raw in _URL_FUNC_RE.findall(text):
        parser._handle_url(raw)

    for match in _FONT_FAMILY_RE.finditer(text):
        parser.used_font_families |= _extract_font_families(match.group(1))

    return (parser.local_refs, parser.external_refs, parser.used_font_families)


def _scan_css_file(
    root_dir: Path, css_path: Path, used_font_families: set[str]
) -> tuple[list[tuple[Path, str]], list[str], list[Path]]:
    """Return (local_refs, external_refs, imported_css_files).

    To avoid over-reporting assets that only appear in unused CSS rules, this
    function only extracts:
    - CSS `@import` dependencies (which the browser will fetch)
    - URLs inside `@font-face` blocks (fonts are fetched when used)

    Inline styles are handled at the HTML layer, not here.
    """

    text = css_path.read_text(encoding="utf-8", errors="replace")

    local_refs: list[tuple[Path, str]] = []
    external_refs: list[str] = []
    imports: list[Path] = []

    def handle_url(raw: str):
        classified = _classify_url(raw)
        if classified is None:
            return
        kind, value = classified
        if kind == "external":
            external_refs.append(value)
            return
        resolved = _resolve_local_path(root_dir, css_path, value)
        local_refs.append((resolved, raw))

    # Only collect URLs from @font-face blocks for font families that appear
    # to be used by the audited pages. This keeps legacy theme icon fonts from
    # polluting the report when the public pages don't actually use them.
    for block in _FONT_FACE_BLOCK_RE.findall(text):
        family_match = _FONT_FAMILY_RE.search(block)
        if family_match:
            families = _extract_font_families(family_match.group(1))
            if families and not (families & used_font_families):
                continue

        for _, raw in _URL_FUNC_RE.findall(block):
            handle_url(raw)

    for match in _IMPORT_RE.finditer(text):
        url = match.group("url")
        classified = _classify_url(url)
        if classified is None:
            continue
        kind, value = classified
        if kind == "external":
            external_refs.append(value)
            continue
        resolved = _resolve_local_path(root_dir, css_path, value)
        imports.append(resolved)
        local_refs.append((resolved, url))

    return (local_refs, external_refs, imports)


def _relpath(root_dir: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(root_dir.resolve()).as_posix()
    except Exception:
        return p.as_posix()


def _format_table(rows: list[tuple[str, str]], header: tuple[str, str]) -> str:
    if not rows:
        return "(none)\n"

    out = [f"| {header[0]} | {header[1]} |", "|---|---|"]
    out.extend([f"| {a} | {b} |" for a, b in rows])
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit render-critical assets for public pages")
    parser.add_argument(
        "--root",
        default=".",
        help="Repository/site root directory (defaults to current working directory)",
    )
    parser.add_argument(
        "--write-broken-assets",
        action="store_true",
        help="Rewrite BROKEN_ASSETS.md with the pruned report",
    )
    args = parser.parse_args(argv)

    root_dir = Path(args.root).resolve()

    page_files: list[Path] = []
    for rel in PUBLIC_PAGES:
        p = (root_dir / rel).resolve()
        if not p.exists():
            raise SystemExit(f"Missing public page: {rel}")
        page_files.append(p)

    local_referrers: dict[Path, set[Referrer]] = {}
    external_referrers: dict[str, set[Referrer]] = {}

    css_to_scan: list[Path] = []
    used_font_families: set[str] = set()

    for page in page_files:
        local_refs, external_refs, page_used_fonts = _scan_html_file(root_dir, page)
        used_font_families |= page_used_fonts
        for resolved, raw in local_refs:
            local_referrers.setdefault(resolved, set()).add(
                Referrer(source_file=_relpath(root_dir, page), raw=raw)
            )

            if resolved.suffix.lower() == ".css":
                css_to_scan.append(resolved)

        for url in external_refs:
            external_referrers.setdefault(url, set()).add(
                Referrer(source_file=_relpath(root_dir, page), raw=url)
            )

    scanned_css: set[Path] = set()
    while css_to_scan:
        css_file = css_to_scan.pop()
        if css_file in scanned_css:
            continue
        scanned_css.add(css_file)

        if not css_file.exists():
            continue

        local_refs, external_refs, imports = _scan_css_file(root_dir, css_file, used_font_families)

        for resolved, raw in local_refs:
            local_referrers.setdefault(resolved, set()).add(
                Referrer(source_file=_relpath(root_dir, css_file), raw=raw)
            )
            if resolved.suffix.lower() == ".css":
                css_to_scan.append(resolved)

        for imported in imports:
            if imported.suffix.lower() == ".css":
                css_to_scan.append(imported)

        for url in external_refs:
            external_referrers.setdefault(url, set()).add(
                Referrer(source_file=_relpath(root_dir, css_file), raw=url)
            )

    missing_local: list[tuple[Path, set[Referrer]]] = []
    for asset_path, refs in local_referrers.items():
        # Ignore references that point outside the repo root (defensive).
        try:
            asset_path.resolve().relative_to(root_dir)
        except Exception:
            continue

        if not asset_path.exists():
            missing_local.append((asset_path, refs))

    missing_local.sort(key=lambda t: _relpath(root_dir, t[0]))

    external_items = sorted(external_referrers.items(), key=lambda t: t[0])

    # Build markdown.
    md: list[str] = []
    md.append("# Broken Assets (Public Pages Only)\n")
    md.append(
        "This file lists only assets required to render the public-facing static pages in this repo.\n"
    )
    md.append("\n## Scope\n")
    for rel in PUBLIC_PAGES:
        md.append(f"- `{rel}`")

    md.append("\n\n## Missing Local Assets\n")
    if missing_local:
        rows: list[tuple[str, str]] = []
        for asset_path, refs in missing_local:
            ref_list = sorted({r.source_file for r in refs})
            rows.append((_relpath(root_dir, asset_path), ", ".join(ref_list)))
        md.append(_format_table(rows, ("Asset", "Referenced From")).rstrip())
        md.append("")
    else:
        md.append("(none)\n")

    md.append("## External Asset Loads\n")
    md.append(
        "These are URLs that the pages/CSS attempt to load directly (e.g. script/link/img/CSS url()).\n"
    )
    if external_items:
        rows = []
        for url, refs in external_items:
            ref_list = sorted({r.source_file for r in refs})
            rows.append((url, ", ".join(ref_list)))
        md.append(_format_table(rows, ("URL", "Referenced From")).rstrip())
        md.append("")
    else:
        md.append("(none)\n")

    output = "\n".join(md).rstrip() + "\n"

    print(
        f"Scanned {len(page_files)} HTML pages, {len(scanned_css)} CSS files. "
        f"Missing local assets: {len(missing_local)}. External asset loads: {len(external_items)}."
    )

    if args.write_broken_assets:
        (root_dir / "BROKEN_ASSETS.md").write_text(output, encoding="utf-8")
        print("Wrote BROKEN_ASSETS.md")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
