#!/usr/bin/env python3
"""
Page Visitor

Reads sites from sites.json, fetches all URLs from sitemaps,
visits each page to trigger view counters in two passes:
  Pass 1 (API): Direct POST to /views/log — fast, completes all URLs first
  Pass 2 (Browser): Playwright headless visit — realistic, JS executes naturally

Usage:
    python visit.py                      # Both passes (API first, then browser)
    python visit.py --dry-run            # List pages only
    python visit.py --api-only           # Skip browser pass entirely
    python visit.py --timeout 180        # Stop browser pass after 180 minutes
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

# Try to import Playwright
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

BASE_DIR = Path(__file__).parent
SITES_FILE = BASE_DIR / "sites.json"

VERCOUNT_API = "https://web.samirpaul.workers.dev/views/log"

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
    "https://www.google.com/search?q=site:samirpaulb.github.io",
    "https://www.bing.com/search?q=",
    "https://duckduckgo.com/?q=",
    "https://github.com/SamirPaulb",
    "https://www.linkedin.com/",
    "https://t.co/",
    "https://www.reddit.com/",
]

TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Los_Angeles",
    "Europe/London", "Europe/Berlin", "Asia/Kolkata",
    "Asia/Tokyo", "Asia/Singapore", "Australia/Sydney",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 2560, "height": 1440},
    {"width": 1280, "height": 720},
]


def load_sites():
    with open(SITES_FILE) as f:
        return json.load(f)


def parse_timeout():
    """Parse --timeout <minutes> from argv. Returns total deadline timestamp or None.
    This is the TOTAL job time limit. Browser pass gets whatever time remains after API pass.
    """
    for i, arg in enumerate(sys.argv):
        if arg == "--timeout" and i + 1 < len(sys.argv):
            try:
                minutes = int(sys.argv[i + 1])
                return time.time() + (minutes * 60)
            except ValueError:
                pass
    return None


# URLs matching these patterns are not content pages — skip them
EXCLUDE_PATTERNS = ["/tags/", "/categories/", "/page/"]


def is_content_url(url):
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


# ─── Pass 1: Direct API ─────────────────────────────────────────────────────

def visit_page_api(url):
    """Direct POST to Vercount /views/log — fast and reliable."""
    ua = random.choice(USER_AGENTS)
    host = url.split("/")[2]
    try:
        resp = requests.post(
            VERCOUNT_API,
            json={"url": url, "isNewUv": True},
            headers={
                "User-Agent": ua,
                "Content-Type": "application/json",
                "Referer": url,
                "Origin": f"https://{host}",
            },
            timeout=10,
        )
        return resp.status_code in (200, 201, 202)
    except:
        return False


def run_api_pass(urls):
    """Pass 1: Hit every URL via direct API POST. Fast, guaranteed to finish."""
    print("\n" + "=" * 60)
    print(" PASS 1: Direct API (POST /views/log)")
    print("=" * 60)

    random.shuffle(urls)
    success = 0
    failed = 0

    for i, url in enumerate(urls):
        if visit_page_api(url):
            success += 1
            slug = url.rstrip("/").split("/")[-1] or url
            print(f"  \u2713 {slug}")
        else:
            failed += 1
            print(f"  \u2717 FAIL: {url}")

        if (i + 1) % 20 == 0:
            print(f"  --- [{i+1}/{len(urls)}] ok={success} fail={failed} ---")

        # Fast pass — just enough delay to not hammer the worker
        time.sleep(random.uniform(0.5, 1.5))

    print(f"\n  Pass 1 done: {success} ok, {failed} failed, {len(urls)} total")
    return success, failed


# ─── Pass 2: Browser (Playwright) ───────────────────────────────────────────

def simulate_human_behavior(page):
    """Simulate realistic human interactions on the page."""
    # Random scroll pattern
    scroll_count = random.randint(2, 5)
    for _ in range(scroll_count):
        scroll_amount = random.randint(200, 600)
        page.mouse.wheel(0, scroll_amount)
        time.sleep(random.uniform(0.5, 1.5))

    # Occasionally move mouse to random positions
    if random.random() < 0.7:
        x = random.randint(100, 800)
        y = random.randint(100, 500)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.3, 0.8))

    # Random dwell time (reading the page)
    time.sleep(random.uniform(2.0, 5.0))


def visit_page_browser(page, url):
    """Visit page in real browser — JS executes, counters fire naturally."""
    try:
        referer = random.choice([r for r in REFERERS if r])
        page.set_extra_http_headers({"Referer": referer})
        page.goto(url, wait_until="domcontentloaded", timeout=25000)

        # Wait for Vercount JS to load and fire
        page.wait_for_timeout(random.randint(1500, 3000))

        # Simulate human reading/scrolling
        simulate_human_behavior(page)

        return True
    except:
        return False


def run_browser_pass(urls, deadline=None):
    """Pass 2: Visit every URL in a real headless browser.
    Stops gracefully if deadline is reached.
    """
    if not PLAYWRIGHT_AVAILABLE:
        print("\n  Skipping browser pass (Playwright not installed)")
        print("  Install: pip install playwright && playwright install chromium")
        return 0, 0

    print("\n" + "=" * 60)
    print(" PASS 2: Browser (Playwright headless)")
    if deadline:
        remaining = int((deadline - time.time()) / 60)
        print(f" Time budget: ~{remaining} minutes")
    print("=" * 60)

    random.shuffle(urls)
    success = 0
    failed = 0
    timed_out = False

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # Create initial context
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport=random.choice(VIEWPORTS),
            locale="en-US",
            timezone_id=random.choice(TIMEZONES),
            color_scheme=random.choice(["light", "dark"]),
        )
        page = context.new_page()

        for i, url in enumerate(urls):
            # Check timeout before each page
            if deadline and time.time() >= deadline:
                timed_out = True
                print(f"\n  Time budget reached after {i} pages. Stopping gracefully.")
                break

            if visit_page_browser(page, url):
                success += 1
                slug = url.rstrip("/").split("/")[-1] or url
                print(f"  \u2713 {slug}")
            else:
                failed += 1
                print(f"  \u2717 FAIL: {url}")

            if (i + 1) % 20 == 0:
                print(f"  --- [{i+1}/{len(urls)}] ok={success} fail={failed} ---")

            # Rotate browser context every 5-10 pages (new "user")
            if (i + 1) % random.randint(5, 10) == 0:
                page.close()
                context.close()
                context = browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport=random.choice(VIEWPORTS),
                    locale=random.choice(["en-US", "en-GB", "en-IN", "en-AU"]),
                    timezone_id=random.choice(TIMEZONES),
                    color_scheme=random.choice(["light", "dark"]),
                )
                page = context.new_page()

            # Realistic delay between pages
            time.sleep(random.uniform(3.0, 6.0))

        page.close()
        context.close()
        browser.close()

    status = "timed out" if timed_out else "completed"
    print(f"\n  Pass 2 {status}: {success} ok, {failed} failed")
    return success, failed


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    api_only = "--api-only" in sys.argv
    deadline = parse_timeout()

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

        # Filter: only content pages, skip tags/categories/pagination
        content_urls = [u for u in urls if is_content_url(u)]
        excluded = len(urls) - len(content_urls)
        print(f"  Found: {len(urls)} total, {len(content_urls)} content pages ({excluded} skipped)")
        all_urls.extend(content_urls)

    all_urls = list(dict.fromkeys(all_urls))
    print(f"\nContent pages to visit: {len(all_urls)}")

    if dry_run:
        for u in all_urls[:10]:
            print(f"  {u}")
        if len(all_urls) > 10:
            print(f"  ... +{len(all_urls)-10} more")
        print(f"\nDone (dry run): {len(all_urls)} pages")
        return

    # Pass 1: Direct API (always runs, no time limit — must complete all URLs)
    api_ok, api_fail = run_api_pass(list(all_urls))

    # Pass 2: Browser (gets whatever time remains from the total budget)
    # Wrapped in try/except so a browser crash never fails the overall job
    browser_ok, browser_fail = 0, 0
    if not api_only:
        try:
            if deadline:
                remaining_min = int((deadline - time.time()) / 60)
                if remaining_min <= 5:
                    print(f"\n  Skipping browser pass — only {remaining_min} min left (need >5)")
                else:
                    print(f"\n  {remaining_min} min remaining for browser pass")
                    browser_ok, browser_fail = run_browser_pass(list(all_urls), deadline)
            else:
                browser_ok, browser_fail = run_browser_pass(list(all_urls), deadline)
        except Exception as e:
            print(f"\n  Browser pass failed with error: {e}")
            print("  (Pass 1 already completed — view counts are safe)")

    # Summary
    print("\n" + "=" * 60)
    print(" SUMMARY")
    print("=" * 60)
    print(f"  Pass 1 (API):     {api_ok} ok, {api_fail} failed")
    if not api_only:
        print(f"  Pass 2 (Browser): {browser_ok} ok, {browser_fail} failed")
    print(f"  Total pages:      {len(all_urls)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
