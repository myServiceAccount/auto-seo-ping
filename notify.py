#!/usr/bin/env python3
"""
Search Engine Notifier

Reads sites from sites.json, fetches sitemaps, finds NEW URLs,
and pings Google/Bing/IndexNow.

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
INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"


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
    url = f"https://www.google.com/ping?sitemap={quote(sitemap_url, safe='')}"
    if dry_run:
        print(f"  [DRY] Google: {url}")
        return
    try:
        r = requests.get(url, timeout=15)
        print(f"  Google ping: {'OK' if r.status_code == 200 else r.status_code}")
    except Exception as e:
        print(f"  Google ping failed: {e}")


def ping_bing(sitemap_url, dry_run=False):
    url = f"https://www.bing.com/ping?sitemap={quote(sitemap_url, safe='')}"
    if dry_run:
        print(f"  [DRY] Bing: {url}")
        return
    try:
        r = requests.get(url, timeout=15)
        print(f"  Bing ping: {'OK' if r.status_code == 200 else r.status_code}")
    except Exception as e:
        print(f"  Bing ping failed: {e}")


def submit_indexnow(host, urls, dry_run=False):
    if not INDEXNOW_KEY or not urls:
        return
    payload = {
        "host": host,
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
        "urlList": urls[:10000],
    }
    if dry_run:
        print(f"  [DRY] IndexNow: {len(urls)} URLs")
        return
    try:
        r = requests.post(INDEXNOW_ENDPOINT, json=payload,
                         headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
        print(f"  IndexNow ({len(urls)} URLs): {'OK' if r.status_code in (200, 202) else r.status_code}")
    except Exception as e:
        print(f"  IndexNow failed: {e}")


def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    if dry_run:
        print("=== DRY RUN ===\n")

    sites = load_sites()
    state = load_state()
    total_new = 0

    for site in sites:
        print(f"\n--- {site['name']} ---")
        sitemap_url = site.get("sitemap") or site.get("rss")
        host = site["host"]

        all_urls = fetch_sitemap_urls(sitemap_url)
        print(f"  Sitemap: {len(all_urls)} URLs")

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

        print(f"  Total unique: {len(all_urls)}")

        prev = set(state["submitted_urls"].get(host, []))
        new_urls = all_urls if force else [u for u in all_urls if u not in prev]

        if new_urls:
            total_new += len(new_urls)
            print(f"  New: {len(new_urls)}")
            for u in new_urls[:5]:
                print(f"    + {u}")
            if len(new_urls) > 5:
                print(f"    ... +{len(new_urls)-5} more")

            ping_google(sitemap_url, dry_run)
            ping_bing(sitemap_url, dry_run)
            submit_indexnow(host, new_urls, dry_run)

            if not dry_run:
                state["submitted_urls"][host] = list(prev | set(all_urls))
        else:
            print(f"  No new content")

    if not dry_run:
        save_state(state)

    print(f"\nDone: {total_new} new URLs notified")


if __name__ == "__main__":
    main()
