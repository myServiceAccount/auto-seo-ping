#!/usr/bin/env python3
"""
Page Visitor

Reads sites from sites.json, fetches all URLs from sitemaps,
visits each page with a fresh browser session to trigger view counters.

Usage:
    python visit.py              # Visit all pages
    python visit.py --dry-run    # List pages only
"""

import json
import os
import sys
import time
import random
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

BASE_DIR = Path(__file__).parent
SITES_FILE = BASE_DIR / "sites.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (iPad; CPU OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
]

REFERERS = [
    "https://www.google.com/",
    "https://www.google.com/search?q=",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
    "https://github.com/",
    "https://www.linkedin.com/",
    "https://t.co/",
    "",
]


def load_sites():
    with open(SITES_FILE) as f:
        return json.load(f)


def fetch_sitemap_urls(sitemap_url):
    urls = []
    try:
        resp = requests.get(sitemap_url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.findall(".//sm:url/sm:loc", ns):
            if loc.text:
                urls.append(loc.text.strip())
        for loc in root.findall(".//sm:sitemap/sm:loc", ns):
            if loc.text:
                urls.extend(fetch_sitemap_urls(loc.text.strip()))
    except Exception as e:
        print(f"  ERROR fetching {sitemap_url}: {e}")
    return urls


def visit_page(url):
    session = requests.Session()
    ua = random.choice(USER_AGENTS)
    referer = random.choice(REFERERS)

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site" if referer else "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if referer:
        headers["Referer"] = referer

    try:
        resp = session.get(url, headers=headers, timeout=25, allow_redirects=True)
        if resp.status_code != 200:
            session.cookies.clear()
            session.close()
            return False

        # Trigger view counter (Vercount Cloudflare Worker)
        try:
            session.get("https://web.samirpaul.workers.dev/views/js",
                       headers={"User-Agent": ua, "Referer": url}, timeout=10)
        except:
            pass

        # Clear all cookies and cached data before next page
        session.cookies.clear()
        session.cache = {}
        session.close()
        del session
        return True
    except:
        try:
            session.cookies.clear()
            session.close()
            del session
        except:
            pass
        return False


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN ===\n")

    sites = load_sites()
    all_urls = []

    for site in sites:
        print(f"--- {site['name']} ---")
        urls = fetch_sitemap_urls(site["sitemap"])

        # Also try RSS if provided
        rss_url = site.get("rss")
        if rss_url:
            try:
                resp = requests.get(rss_url, timeout=30)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                for item in root.iter("item"):
                    link = item.find("link")
                    if link is not None and link.text:
                        url = link.text.strip()
                        if url not in urls:
                            urls.append(url)
            except:
                pass

        print(f"  URLs: {len(urls)}")
        all_urls.extend(urls)

    all_urls = list(dict.fromkeys(all_urls))
    print(f"\nTotal pages: {len(all_urls)}")

    if dry_run:
        for u in all_urls[:10]:
            print(f"  {u}")
        if len(all_urls) > 10:
            print(f"  ... +{len(all_urls)-10} more")
        print(f"\nDone (dry run): {len(all_urls)} pages")
        return

    # Shuffle and visit
    random.shuffle(all_urls)
    success = 0
    failed = 0

    for i, url in enumerate(all_urls):
        if visit_page(url):
            success += 1
        else:
            failed += 1
            print(f"  FAIL: {url}")

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(all_urls)}] ok={success} fail={failed}")

        time.sleep(random.uniform(1.5, 4.0))

    print(f"\nDone: {success} visited, {failed} failed, {len(all_urls)} total")


if __name__ == "__main__":
    main()
