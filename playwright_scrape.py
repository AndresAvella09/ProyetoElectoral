"""Playwright-based X/Twitter search scraper.

This script runs outside Jupyter to avoid asyncio/subprocess conflicts on Windows.
It saves results to CSV and supports optional cookie authentication via X_COOKIES_JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
from playwright.sync_api import sync_playwright


def _to_int_count(text: str) -> int:
    if not text:
        return 0
    t = text.strip().upper().replace(",", "")
    m = re.match(r"^([0-9]*\.?[0-9]+)([KMB])?$", t)
    if not m:
        digits = re.sub(r"[^0-9]", "", t)
        return int(digits) if digits else 0
    value = float(m.group(1))
    suffix = m.group(2)
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(value * mult)


def _extract_tweet_id(article) -> str | None:
    anchors = article.locator('a[href*="/status/"]')
    for i in range(min(anchors.count(), 8)):
        href = anchors.nth(i).get_attribute("href") or ""
        m = re.search(r"/status/(\d+)", href)
        if m:
            return m.group(1)
    return None


def _extract_username(article) -> str | None:
    anchors = article.locator('a[href*="/status/"]')
    for i in range(min(anchors.count(), 8)):
        href = anchors.nth(i).get_attribute("href") or ""
        m = re.search(r"^/([^/]+)/status/\d+", href)
        if m:
            return m.group(1)
    return None


def _extract_text(article) -> str:
    text_node = article.locator('div[data-testid="tweetText"]')
    if text_node.count() > 0:
        return text_node.first.inner_text().strip()
    lang_node = article.locator("div[lang]")
    if lang_node.count() > 0:
        return lang_node.first.inner_text().strip()
    return ""


def _extract_action_count(article, action: str) -> int:
    btn = article.locator(f'div[data-testid="{action}"]')
    if btn.count() == 0:
        return 0
    raw = btn.first.inner_text().strip()
    return _to_int_count(raw)


def _load_cookies_from_env(env_var: str) -> list[dict[str, Any]]:
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return []
    cookies = json.loads(raw)
    normalized: list[dict[str, Any]] = []
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain")
        if not name or value is None or not domain:
            continue
        domain = domain.replace(".twitter.com", ".x.com").replace("twitter.com", "x.com")
        normalized.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": c.get("path", "/"),
                "expires": int(c.get("expirationDate", -1)) if c.get("expirationDate") else -1,
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", True)),
                "sameSite": "None" if c.get("sameSite") == "no_restriction" else "Lax",
            }
        )
    return normalized


def scrape_x_search_playwright(
    query: str,
    limit: int = 500,
    out_csv: str = "tweets_colombia.csv",
    headless: bool = True,
    scroll_pause: float = 1.2,
    max_scrolls: int = 120,
    chunk_size: int = 100,
    auth_env_var: str = "X_COOKIES_JSON",
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    out_path = Path(out_csv)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(locale="es-CO")

        cookies = _load_cookies_from_env(auth_env_var)
        if cookies:
            context.add_cookies(cookies)

        page = context.new_page()
        search_url = f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"
        page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(int(scroll_pause * 1000))

        last_height = 0
        stagnant_rounds = 0

        for _ in range(max_scrolls):
            articles = page.locator('article[role="article"]')
            n = articles.count()

            for i in range(n):
                art = articles.nth(i)
                tweet_id = _extract_tweet_id(art)
                if not tweet_id or tweet_id in seen_ids:
                    continue
                seen_ids.add(tweet_id)

                records.append(
                    {
                        "id": tweet_id,
                        "username": _extract_username(art),
                        "content": _extract_text(art),
                        "likes": _extract_action_count(art, "like"),
                        "retweets": _extract_action_count(art, "retweet"),
                    }
                )

                if len(records) >= limit:
                    break

            if len(records) >= limit:
                break

            if len(records) and len(records) % chunk_size == 0:
                pd.DataFrame(records).drop_duplicates(subset=["id"]).to_csv(out_path, index=False)

            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(int(scroll_pause * 1000))
            new_height = page.evaluate("document.body.scrollHeight")

            if new_height == last_height:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            last_height = new_height

            if stagnant_rounds >= 4:
                break

        browser.close()

    df = pd.DataFrame(records).drop_duplicates(subset=["id"]).head(limit)
    df.to_csv(out_path, index=False)
    print(f"Dataset guardado: {out_path.resolve()} ({len(df)} filas)")
    return df


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="X/Twitter search scraper using Playwright")
    parser.add_argument("--query", required=True, help="Search query for X")
    parser.add_argument("--limit", type=int, default=500, help="Max tweets to collect")
    parser.add_argument("--out", default="tweets_colombia.csv", help="Output CSV path")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--headful", action="store_true", help="Run browser with UI")
    parser.add_argument("--max-scrolls", type=int, default=120, help="Max scroll iterations")
    parser.add_argument("--scroll-pause", type=float, default=1.2, help="Pause between scrolls (seconds)")
    parser.add_argument("--chunk-size", type=int, default=100, help="Save every N records")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    headless = args.headless and not args.headful
    scrape_x_search_playwright(
        query=args.query,
        limit=args.limit,
        out_csv=args.out,
        headless=headless,
        scroll_pause=args.scroll_pause,
        max_scrolls=args.max_scrolls,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()
