#!/usr/bin/env python3
"""
Search Engine & AI Crawler Notifier

Reads sites from sites.json, fetches sitemaps, finds NEW URLs,
and submits to all available search engines and AI crawlers.

Targets:
  - IndexNow (Bing, Yandex, Naver, Seznam, Yep) — direct submission
  - Google sitemap ping (legacy, best effort)
  - Bing sitemap ping (legacy, best effort)

AI crawlers that benefit (they use Bing/Yandex index or crawl sitemaps):
  - Microsoft Copilot (uses Bing index — IndexNow directly helps)
  - ChatGPT/OpenAI GPTBot (crawls sitemap.xml)
  - Perplexity PerplexityBot (crawls sitemap.xml)
  - You.com YouBot (crawls sitemap.xml)
  - Claude/Anthropic ClaudeBot (crawls sitemap.xml)
  - Phind (crawls sitemap.xml)
  - Google Gemini (uses Google index)

Usage:
    python notify.py              # Normal (new URLs only)
    python notify.py --dry-run    # Don't submit anything
    python notify.py --force      # Submit all URLs
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

BASE_DIR = Path(__file__).parent
SITES_FILE = BASE_DIR / "sites.json"
STATE_FILE = BASE_DIR / "state.json"
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "40ec972f18a54a3aa2bcc40b7b46a64c")

# All IndexNow endpoints — submit to each directly for maximum coverage
# api.indexnow.org distributes, but direct submission is more reliable
INDEXNOW_ENDPOINTS = [
    ("Bing", "https://www.bing.com/indexnow"),
    ("Yandex", "https://yandex.com/indexnow"),
    ("Naver", "https://searchadvisor.naver.com/indexnow"),
    ("Seznam", "https://search.seznam.cz/indexnow"),
    ("Yep", "https://indexnow.yep.com/indexnow"),
]

# URLs matching these patterns are skipped (not real content pages)
EXCLUDE_PATTERNS = ["/tags/", "/categories/", "/page/"]


def load_sites():
    with open(SITES_FILE) as f:
        return json.load(f)


def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            if "submitted_urls" not in data:
                data["submitted_urls"] = {}
            return data
        except (json.JSONDecodeError, KeyError):
            pass
    return {"submitted_urls": {}, "last_run": None}


def save_state(state):
    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_content_url(url):
    """Filter out tag/category/pagination URLs — only keep real content."""
    for pattern in EXCLUDE_PATTERNS:
        if pattern in url:
            return False
    return True


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


def ping_google(sitemap_url, dry_run=False):
    """Ping Google to re-crawl sitemap (legacy, best effort)."""
    url = f"https://www.google.com/ping?sitemap={quote(sitemap_url, safe='')}"
    if dry_run:
        print(f"  [DRY] Google sitemap ping")
        return
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            print(f"  Google: OK")
    except:
        pass


def ping_bing(sitemap_url, dry_run=False):
    """Ping Bing sitemap endpoint (legacy, best effort)."""
    url = f"https://www.bing.com/ping?sitemap={quote(sitemap_url, safe='')}"
    if dry_run:
        print(f"  [DRY] Bing sitemap ping")
        return
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            print(f"  Bing sitemap: OK")
    except:
        pass


def submit_indexnow_all(host, urls, dry_run=False):
    """Submit URLs to ALL IndexNow endpoints (Bing, Yandex, Naver, Seznam, Yep)."""
    if not INDEXNOW_KEY or not urls:
        return

    payload = {
        "host": host,
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
        "urlList": urls[:10000],
    }

    if dry_run:
        print(f"  [DRY] IndexNow → {len(urls)} URLs to {len(INDEXNOW_ENDPOINTS)} engines")
        return

    for name, endpoint in INDEXNOW_ENDPOINTS:
        try:
            r = requests.post(endpoint, json=payload,
                             headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
            status = "OK" if r.status_code in (200, 202) else f"{r.status_code}"
            print(f"  IndexNow → {name}: {status}")
        except Exception as e:
            print(f"  IndexNow → {name}: FAILED ({e})")
        time.sleep(1)  # Brief pause between endpoints


def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    if dry_run:
        print("=== DRY RUN ===\n")

    sites = load_sites()
    state = load_state()
    total_new = 0

    for site in sites:
        print(f"\n{'='*50}")
        print(f" {site['name']}")
        print(f"{'='*50}")
        sitemap_url = site.get("sitemap") or site.get("rss")
        host = site["host"]

        # Fetch all URLs from sitemap
        all_urls = fetch_sitemap_urls(sitemap_url)

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
                        if url not in all_urls:
                            all_urls.append(url)
            except:
                pass

        # Filter out non-content URLs (tags, categories, pagination)
        content_urls = [u for u in all_urls if is_content_url(u)]
        excluded = len(all_urls) - len(content_urls)
        print(f"  Sitemap: {len(all_urls)} total, {len(content_urls)} content pages ({excluded} excluded)")

        # Find new URLs
        prev = set(state["submitted_urls"].get(host, []))
        new_urls = content_urls if force else [u for u in content_urls if u not in prev]

        if new_urls:
            total_new += len(new_urls)
            print(f"  New URLs: {len(new_urls)}")
            for u in new_urls[:5]:
                print(f"    + {u}")
            if len(new_urls) > 5:
                print(f"    ... +{len(new_urls)-5} more")

            print(f"\n  Pinging search engines...")
            ping_google(sitemap_url, dry_run)
            ping_bing(sitemap_url, dry_run)

            print(f"  Submitting to IndexNow (Bing, Yandex, Naver, Seznam, Yep)...")
            submit_indexnow_all(host, new_urls, dry_run)

            if not dry_run:
                state["submitted_urls"][host] = list(prev | set(content_urls))
        else:
            print(f"  No new content — all URLs already submitted")

    if not dry_run:
        save_state(state)

    print(f"\n{'='*50}")
    print(f" DONE: {total_new} new URLs → Bing, Yandex, Naver, Seznam, Yep")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
