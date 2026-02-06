#!/usr/bin/env python3
"""Build fully-local static pages from mirrored WordPress HTML snapshots.

Outputs:
- contact-us/index.html
- irresistible/index.html
- privacy-policy/index.html

Also updates:
- index.html (in place)

The goal is to remove external/WordPress-only head dependencies (analytics, Yoast,
wp-json links, emoji script, trackers) and ensure CSS/JS/img/font references are
self-hosted and path-correct.
"""

from __future__ import annotations

import re
from pathlib import Path
import urllib.request
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


REMOVE_PATTERNS: list[re.Pattern[str]] = [
    # Old IE shims (remote)
    re.compile(r"(?is)<!--\[if[^\]]+\]>.*?<!\[endif\]-->", re.MULTILINE),
    # Google Analytics inline loader block
    re.compile(
        r"(?is)<script>\s*\(function\(i,s,o,g,r,a,m\)\{.*?ga\('send',\s*'pageview'\);\s*</script>\s*",
        re.MULTILINE,
    ),
    # Yoast schema JSON-LD
    re.compile(
        r"(?is)<script[^>]+class=\"yoast-schema-graph\"[^>]*>.*?</script>\s*",
        re.MULTILINE,
    ),
    # WP emoji bootstrapper
    re.compile(
        r"(?is)<script[^>]*>\s*window\._wpemojiSettings\s*=\s*\{.*?</script>\s*",
        re.MULTILINE,
    ),
    # s.w.org DNS-prefetch
    re.compile(r"(?is)<link[^>]+href=\"//s\.w\.org\"[^>]*/>\s*", re.MULTILINE),
    # WordPress API / oEmbed / manifest links
    re.compile(r"(?is)<link[^>]+rel=\"https://api\.w\.org/\"[^>]*/>\s*", re.MULTILINE),
    re.compile(r"(?is)<link[^>]+href=\"https?://www\.jujuhq\.com/wp-json/[^\"]*\"[^>]*/>\s*", re.MULTILINE),
    re.compile(r"(?is)<link[^>]+href=\"https?://www\.jujuhq\.com/xmlrpc\.php\?rsd\"[^>]*/>\s*", re.MULTILINE),
    re.compile(r"(?is)<link[^>]+href=\"https?://www\.jujuhq\.com/wp-includes/wlwmanifest\.xml\"[^>]*/>\s*", re.MULTILINE),
    re.compile(r"(?is)<link[^>]+type=\"application/json\+oembed\"[^>]*/>\s*", re.MULTILINE),
    re.compile(r"(?is)<link[^>]+type=\"text/xml\+oembed\"[^>]*/>\s*", re.MULTILINE),
    # WP generator + shortlink
    re.compile(r"(?is)<meta[^>]+name=\"generator\"[^>]*/>\s*", re.MULTILINE),
    re.compile(r"(?is)<link[^>]+rel=\"shortlink\"[^>]*/>\s*", re.MULTILINE),
    # External tile image
    re.compile(r"(?is)<meta[^>]+name=\"msapplication-TileImage\"[^>]*/>\s*", re.MULTILINE),
    # qlzn tracker
    re.compile(r"(?is)<script[^>]+qlzn6i1l\.com[^>]*></script>\s*", re.MULTILINE),
    re.compile(r"(?is)<noscript>\s*<img[^>]+qlzn6i1l\.com[^>]*>\s*</noscript>\s*", re.MULTILINE),
    # Thrive global vars often include remote images (gravatar / wp-content/plugins)
    re.compile(r"(?is)<style[^>]+id=\"tve_global_variables\"[^>]*>.*?</style>\s*", re.MULTILINE),
]


def sanitize_common(html: str) -> str:
    for pat in REMOVE_PATTERNS:
        html = pat.sub("", html)

    # Remove any remaining explicit GA external include.
    html = re.sub(
        r'(?is)<script[^>]+src=\"https?://www\.google-analytics\.com/[^\"]+\"[^>]*></script>\s*',
        "",
        html,
    )

    # Remove any Google Fonts link tags (we use assets/css/fonts.css).
    html = re.sub(
        r'(?is)<link[^>]+href=\"assets/css/css\"[^>]*>\s*',
        "",
        html,
    )

    return html


def rewrite_internal_links(html: str) -> str:
    # Canonical/original host -> local paths
    html = html.replace('href="https://www.jujuhq.com/"', 'href="/"')
    html = html.replace('href="http://www.jujuhq.com/"', 'href="/"')

    html = html.replace('href="https://www.jujuhq.com/contact-us/"', 'href="/contact-us/"')
    html = html.replace('href="http://www.jujuhq.com/contact-us/"', 'href="/contact-us/"')

    html = html.replace('href="https://www.jujuhq.com/irresistible/"', 'href="/irresistible/"')
    html = html.replace('href="http://www.jujuhq.com/irresistible/"', 'href="/irresistible/"')

    html = html.replace('href="https://www.jujuhq.com/privacy-policy/"', 'href="/privacy-policy/"')
    html = html.replace('href="http://www.jujuhq.com/privacy-policy/"', 'href="/privacy-policy/"')

    # Some links appear without trailing slash
    html = html.replace('href="http://jujuhq.com/privacy-policy#cookies"', 'href="/privacy-policy/#cookies"')
    html = html.replace('href="http://jujuhq.com/privacy-policy"', 'href="/privacy-policy/"')

    return html


def ensure_fonts_link(html: str, href_value: str) -> str:
    # Try to insert fonts link early in <head> for predictable cascade.
    fonts_tag = f'<link href="{href_value}" rel="stylesheet" type="text/css"/>'

    if href_value in html:
        return html

    m = re.search(r"(?is)<meta[^>]+charset=\"[^\"]+\"[^>]*/?>", html)
    if m:
        insert_at = m.end()
        return html[:insert_at] + "\n" + fonts_tag + html[insert_at:]

    m = re.search(r"(?is)<head[^>]*>", html)
    if m:
        insert_at = m.end()
        return html[:insert_at] + "\n" + fonts_tag + html[insert_at:]

    return fonts_tag + "\n" + html


_WP_UPLOAD_URL_RE = re.compile(r"(?i)https?://www\.jujuhq\.com/wp-content/uploads/[^'\"\)\s>]+")


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


def localize_wp_uploads(html: str, replacement_prefix: str) -> str:
    """Download wp-content/uploads assets and rewrite them to local assets/img paths."""

    img_dir = ROOT / "assets" / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    urls = sorted(set(_WP_UPLOAD_URL_RE.findall(html)))
    for url in urls:
        filename = Path(urlparse(url).path).name
        if not filename:
            continue

        local_path = img_dir / filename
        if not local_path.exists():
            try:
                local_path.write_bytes(_http_get_bytes(url))
            except Exception:
                continue

        html = html.replace(url, f"{replacement_prefix}{filename}")

    return html


def rewrite_asset_paths_for_subdir(html: str) -> str:
    # In /contact-us/ etc, assets are one level up.
    html = re.sub(r'(?i)href="assets/', 'href="../assets/', html)
    html = re.sub(r'(?i)src="assets/', 'src="../assets/', html)

    # Also fix inline CSS url(assets/..)
    html = re.sub(r"(?i)url\((['\"]?)assets/", r"url(\1../assets/", html)
    return html


def remove_canonical(html: str) -> str:
    return re.sub(r'(?is)<link[^>]+rel=\"canonical\"[^>]*/>\s*', "", html)


def build_page(src: Path, dest: Path, fonts_href: str, subdir_assets: bool) -> None:
    html = src.read_text(encoding="utf-8", errors="replace")

    html = sanitize_common(html)
    html = remove_canonical(html)
    html = rewrite_internal_links(html)

    html = localize_wp_uploads(
        html,
        replacement_prefix=("../assets/img/" if subdir_assets else "assets/img/"),
    )

    if subdir_assets:
        html = rewrite_asset_paths_for_subdir(html)

    html = ensure_fonts_link(html, fonts_href)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")


def main() -> None:
    # Internal pages -> root subdirectories
    build_page(
        src=ROOT / "pages" / "contact-us.html",
        dest=ROOT / "contact-us" / "index.html",
        fonts_href="../assets/css/fonts.css",
        subdir_assets=True,
    )
    build_page(
        src=ROOT / "pages" / "irresistible.html",
        dest=ROOT / "irresistible" / "index.html",
        fonts_href="../assets/css/fonts.css",
        subdir_assets=True,
    )
    build_page(
        src=ROOT / "pages" / "privacy-policy.html",
        dest=ROOT / "privacy-policy" / "index.html",
        fonts_href="../assets/css/fonts.css",
        subdir_assets=True,
    )

    # Home page: update in place
    index_path = ROOT / "index.html"
    index_html = index_path.read_text(encoding="utf-8", errors="replace")
    index_html = sanitize_common(index_html)
    index_html = remove_canonical(index_html)
    index_html = rewrite_internal_links(index_html)
    index_html = localize_wp_uploads(index_html, replacement_prefix="assets/img/")
    index_html = ensure_fonts_link(index_html, "assets/css/fonts.css")
    index_path.write_text(index_html, encoding="utf-8")

    print("Built: contact-us/index.html")
    print("Built: irresistible/index.html")
    print("Built: privacy-policy/index.html")
    print("Updated: index.html")


if __name__ == "__main__":
    main()
