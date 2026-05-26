#!/usr/bin/env python3
"""Scrape modulargreenhouses.com (your own Wix site) for images and text.

Run this on a machine that can reach the site (not the Claude sandbox, whose
network blocks it):

    pip install requests
    python3 scripts/scrape_site.py

Outputs (git-ignored):
    scraped/images/      every static.wixstatic.com image, at full resolution
    scraped/pages.json   per-page title / description / text / image list
    scraped/images.json  manifest mapping downloaded files to source URLs

Notes
-----
* Wix blocks default bot user-agents, so we send a browser one.
* Wix is JS-heavy, but it embeds image URLs and SEO text in the initial HTML,
  which is what we parse. If a page's gallery is purely JS-rendered and an image
  is missed, install Playwright and re-run with --render (optional, heavier).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    raise SystemExit("This script needs 'requests'. Install it with: pip install requests")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Any static.wixstatic.com asset (media photos + shapes/svgs).
ASSET_RE = re.compile(r"https://static\.wixstatic\.com/(?:media|shapes)/[^\s\"'\\)]+")
IMG_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|svg|avif)", re.I)

session = requests.Session()
session.headers.update(HEADERS)


def fetch(url: str):
    for attempt in range(4):
        try:
            r = session.get(url, timeout=30)
            return r
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"  retry in {wait}s ({exc}) {url}")
            time.sleep(wait)
    return None


def discover_urls(base: str) -> list[str]:
    """Collect page URLs from sitemap(s), falling back to a homepage crawl."""
    urls: set[str] = {base + "/"}
    seen: set[str] = set()
    queue = [urljoin(base, "/sitemap.xml")]
    while queue:
        sm = queue.pop()
        if sm in seen:
            continue
        seen.add(sm)
        r = fetch(sm)
        if not r or r.status_code != 200:
            continue
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text):
            if loc.endswith(".xml"):
                queue.append(loc)
            else:
                urls.add(loc)

    if len(urls) <= 1:
        # No usable sitemap — crawl internal links from the homepage one level deep.
        host = urlparse(base).netloc
        r = fetch(base + "/")
        if r and r.status_code == 200:
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text):
                full = urljoin(base, href)
                if urlparse(full).netloc == host and "#" not in full:
                    urls.add(full.split("?")[0])
    return sorted(urls)


def original_image_url(url: str) -> str:
    """Drop Wix's on-the-fly transform (/v1/fill/...) to get the original file."""
    return url.split("/v1/")[0]


def extract(html: str):
    title_m = re.search(r"<title>([^<]*)</title>", html, re.I)
    desc_m = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', html, re.I
    )
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", body).strip()

    images = set()
    for raw in ASSET_RE.findall(html):
        u = original_image_url(raw).rstrip(").,'\";")
        if IMG_EXT_RE.search(u):
            images.add(u)
    return (
        title_m.group(1).strip() if title_m else "",
        desc_m.group(1).strip() if desc_m else "",
        text[:8000],
        sorted(images),
    )


def safe_name(url: str) -> str:
    tail = url.split("/media/")[-1].split("/shapes/")[-1]
    name = re.sub(r"[^A-Za-z0-9._~-]", "_", tail)[:120]
    if not IMG_EXT_RE.search(name):
        name += ".img"
    return name


def main():
    ap = argparse.ArgumentParser(description="Scrape modulargreenhouses.com")
    ap.add_argument("--base", default="https://www.modulargreenhouses.com")
    ap.add_argument("--out", default="scraped")
    ap.add_argument("--max-pages", type=int, default=200)
    args = ap.parse_args()

    out = Path(args.out)
    img_dir = out / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    urls = discover_urls(args.base)[: args.max_pages]
    print(f"Discovered {len(urls)} page(s)")

    pages = []
    all_images: set[str] = set()
    for u in urls:
        r = fetch(u)
        if not r or r.status_code != 200:
            print(f"  [{r.status_code if r else 'ERR'}] {u}")
            continue
        title, desc, text, images = extract(r.text)
        all_images.update(images)
        pages.append({"url": u, "title": title, "description": desc, "text": text, "images": images})
        print(f"  [200] {u} -> {len(images)} image(s)")
        time.sleep(0.4)

    manifest = []
    for url in sorted(all_images):
        dest = img_dir / safe_name(url)
        if dest.exists():
            manifest.append({"url": url, "file": str(dest)})
            continue
        r = fetch(url)
        if r and r.status_code == 200 and r.content:
            dest.write_bytes(r.content)
            manifest.append({"url": url, "file": str(dest), "bytes": len(r.content)})
            print(f"  saved {dest.name} ({len(r.content):,} bytes)")
        else:
            print(f"  [skip] {url}")
        time.sleep(0.25)

    (out / "pages.json").write_text(json.dumps(pages, indent=2))
    (out / "images.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nDone: {len(pages)} pages, {len(manifest)} images -> {out}/")
    print("Review scraped/pages.json and scraped/images/, then share or commit them.")


if __name__ == "__main__":
    main()
