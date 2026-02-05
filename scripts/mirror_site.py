import os
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://jujuhq.com"
ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "index.html"
BROKEN_LOG = ROOT / "BROKEN_ASSETS.md"
ASSETS = ROOT / "assets"
CSS_DIR = ASSETS / "css"
JS_DIR = ASSETS / "js"
IMG_DIR = ASSETS / "img"
FONTS_DIR = ASSETS / "fonts"
PAGES_DIR = ROOT / "pages"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
})

def log_broken(asset_type: str, url: str, reason: str):
    with open(BROKEN_LOG, "a") as f:
        f.write(f"{asset_type} | {url} | {reason}\n")


def is_same_origin(url: str) -> bool:
    try:
        u = urllib.parse.urlparse(url)
        if not u.netloc:
            return True  # relative
        return u.netloc == urllib.parse.urlparse(BASE_URL).netloc
    except Exception:
        return False


def absolutize(url: str) -> str:
    if not url:
        return url
    if url.startswith("//"):
        return "https:" + url
    return urllib.parse.urljoin(BASE_URL, url)


def local_path_for(url: str, content_type: str | None) -> Path:
    parsed = urllib.parse.urlparse(url)
    name = os.path.basename(parsed.path) or "index"
    ext = os.path.splitext(name)[1].lower()
    # Decide dir by extension or content-type
    if ext in {".css"} or (content_type and "text/css" in content_type):
        return CSS_DIR / name
    if ext in {".js"} or (content_type and "javascript" in content_type):
        return JS_DIR / name
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"} or (content_type and "image" in content_type):
        return IMG_DIR / name
    if ext in {".woff", ".woff2", ".ttf", ".otf"} or (content_type and "font" in content_type):
        return FONTS_DIR / name
    # Fallback by extension
    if ext:
        if ext in {".map"}:
            return JS_DIR / name
        if ext in {".ico"}:
            return IMG_DIR / name
    # Unknown -> images as default
    return IMG_DIR / name


def download(url: str) -> tuple[Path | None, str | None]:
    abs_url = absolutize(url)
    try:
        resp = session.get(abs_url, timeout=20)
        if resp.status_code != 200:
            log_broken("ASSET", abs_url, f"HTTP {resp.status_code}")
            return None, None
        ctype = resp.headers.get("Content-Type", "")
        local = local_path_for(abs_url, ctype)
        local.parent.mkdir(parents=True, exist_ok=True)
        with open(local, "wb") as f:
            f.write(resp.content)
        return local, ctype
    except requests.RequestException as e:
        log_broken("ASSET", abs_url, f"{type(e).__name__}: {e}")
        return None, None


CSS_URL_RE = re.compile(r"url\(([^)]+)\)")


def process_css_file(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    urls = []
    for m in CSS_URL_RE.finditer(text):
        raw = m.group(1).strip("'\" ")
        if raw.startswith("data:"):
            continue
        urls.append(raw)
    for u in urls:
        abs_u = absolutize(u)
        # Only mirror same-origin assets
        if is_same_origin(abs_u):
            downloaded, ctype = download(abs_u)
            # No rewrite inside CSS for now, paths likely relative; keeping external references if any



def extract_asset_urls(soup: BeautifulSoup) -> list[tuple[str, str, str]]:
    assets = []
    # tag, attr, url
    for link in soup.find_all("link"):
        href = (link.get("href") or "").strip()
        rel = (link.get("rel") or [])
        if href and any(r in {"stylesheet", "icon", "preload"} for r in rel):
            assets.append(("link", "href", href))
    for script in soup.find_all("script"):
        src = (script.get("src") or "").strip()
        if src:
            assets.append(("script", "src", src))
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if src:
            assets.append(("img", "src", src))
        srcset = (img.get("srcset") or "").strip()
        if srcset:
            for candidate in srcset.split(","):
                u = candidate.strip().split(" ")[0]
                if u:
                    assets.append(("img", "srcset", u))
    for source in soup.find_all("source"):
        srcset = (source.get("srcset") or "").strip()
        if srcset:
            for candidate in srcset.split(","):
                u = candidate.strip().split(" ")[0]
                if u:
                    assets.append(("source", "srcset", u))
    # Open Graph / meta images
    for meta in soup.find_all("meta"):
        if meta.get("property") in {"og:image", "twitter:image"}:
            c = (meta.get("content") or "").strip()
            if c:
                assets.append(("meta", "content", c))
    return assets


def extract_internal_links(soup: BeautifulSoup) -> list[str]:
    links: list[str] = []
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        if href.startswith("mailto:") or href.startswith("tel:"):
            continue
        abs_url = absolutize(href)
        if is_same_origin(abs_url):
            links.append(abs_url)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for u in links:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def save_page(url: str, html: str) -> Path:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    if not path or path.endswith("/"):
        out_dir = PAGES_DIR / (path.strip("/") or "home")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "index.html"
    else:
        out_dir = PAGES_DIR / os.path.dirname(path.strip("/"))
        out_dir.mkdir(parents=True, exist_ok=True)
        name = os.path.basename(path)
        # ensure .html extension if none
        if "." not in name:
            name = name + ".html"
        out_file = out_dir / name
    out_file.write_text(html, encoding="utf-8", errors="ignore")
    return out_file


def main():
    if not INDEX_PATH.exists():
        print(f"Missing {INDEX_PATH}")
        sys.exit(1)
    html = INDEX_PATH.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    assets = extract_asset_urls(soup)

    # Download same-origin assets and optionally verify external ones
    rewrite_map: dict[str, str] = {}
    for tag, attr, url in assets:
        abs_url = absolutize(url)
        if is_same_origin(abs_url):
            local, ctype = download(abs_url)
            if local:
                # Create a relative path from root
                rel = os.path.relpath(local, ROOT)
                rewrite_map[url] = rel
        else:
            # Validate external availability
            try:
                r = session.head(abs_url, allow_redirects=True, timeout=15)
                if r.status_code >= 400:
                    log_broken("EXTERNAL", abs_url, f"HTTP {r.status_code}")
            except requests.RequestException as e:
                log_broken("EXTERNAL", abs_url, f"{type(e).__name__}: {e}")

    # Process downloaded CSS for nested assets
    for p in CSS_DIR.glob("*.css"):
        process_css_file(p)

    # Rewrite index.html asset references to local ones
    # Only rewrite exact matches (original URL as it appeared in attributes)
    for tag, attr, url in assets:
        local_rel = rewrite_map.get(url)
        if not local_rel:
            continue
        # Find all matching tags again to replace
        for el in soup.find_all(tag):
            if (el.get(attr) or "").strip() == url:
                el[attr] = local_rel

    # Save a backup of original and write rewritten
    backup = ROOT / "index.remote.html"
    backup.write_text(html, encoding="utf-8", errors="ignore")
    INDEX_PATH.write_text(str(soup), encoding="utf-8", errors="ignore")

    print("Mirroring complete. Assets downloaded and paths rewritten where possible.")

    # Crawl internal links from homepage and mirror those pages
    internal_links = extract_internal_links(soup)
    for link in internal_links:
        try:
            r = session.get(link, timeout=20)
            if r.status_code != 200:
                log_broken("PAGE", link, f"HTTP {r.status_code}")
                continue
            ctype = r.headers.get("Content-Type", "")
            if "text/html" not in ctype:
                # Not an HTML page; if same-origin, download as asset
                if is_same_origin(link):
                    download(link)
                else:
                    log_broken("EXTERNAL", link, f"Non-HTML content-type: {ctype}")
                continue
            page_html = r.text
            page_soup = BeautifulSoup(page_html, "lxml")
            page_assets = extract_asset_urls(page_soup)
            # Download and rewrite same-origin assets for this page
            rewrite_map: dict[str, str] = {}
            for tag, attr, url in page_assets:
                abs_url = absolutize(url)
                if is_same_origin(abs_url):
                    local, ctype = download(abs_url)
                    if local:
                        rel = os.path.relpath(local, ROOT)
                        rewrite_map[url] = rel
                else:
                    # Validate external availability
                    try:
                        hr = session.head(abs_url, allow_redirects=True, timeout=15)
                        if hr.status_code >= 400:
                            log_broken("EXTERNAL", abs_url, f"HTTP {hr.status_code}")
                    except requests.RequestException as e:
                        log_broken("EXTERNAL", abs_url, f"{type(e).__name__}: {e}")

            # Process downloaded CSS after this page
            for p in CSS_DIR.glob("*.css"):
                process_css_file(p)

            for tag, attr, url in page_assets:
                local_rel = rewrite_map.get(url)
                if local_rel:
                    for el in page_soup.find_all(tag):
                        if (el.get(attr) or "").strip() == url:
                            el[attr] = local_rel

            out_file = save_page(link, str(page_soup))
            print(f"Saved page: {out_file}")
        except requests.RequestException as e:
            log_broken("PAGE", link, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
