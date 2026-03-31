"""Playwright-based X/Twitter search scraper.

This script runs outside Jupyter to avoid asyncio/subprocess conflicts on Windows.
It saves results to CSV and uses a real Microsoft Edge profile (no automated login).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
from playwright.sync_api import sync_playwright

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


logger = logging.getLogger("x_scraper")


def _configure_logging(level: str, log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


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


def _save_debug(page, debug_dir: str | None, base_name: str) -> None:
    if not debug_dir:
        return
    out_dir = Path(debug_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(out_dir / f"{base_name}.png"))
        with open(out_dir / f"{base_name}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception as e:
        logger.debug(f"Failed to save debug artifact {base_name}: {e}")


def _extract_tweet_id_from_href(href: str) -> str | None:
    if not href:
        return None
    m = re.search(r"/status/(\d+)", href)
    return m.group(1) if m else None


def _extract_username_from_href(href: str) -> str | None:
    if not href:
        return None
    m = re.search(r"/([^/]+)/status/\d+", href)
    return m.group(1) if m else None


def _extract_tweet_id(article) -> str | None:
    anchors = article.locator('a[href*="/status/"]')
    for i in range(min(anchors.count(), 8)):
        href = anchors.nth(i).get_attribute("href") or ""
        tweet_id = _extract_tweet_id_from_href(href)
        if tweet_id:
            return tweet_id
    return None


def _extract_username(article) -> str | None:
    anchors = article.locator('a[href*="/status/"]')
    for i in range(min(anchors.count(), 8)):
        href = anchors.nth(i).get_attribute("href") or ""
        username = _extract_username_from_href(href)
        if username:
            return username
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


def _get_real_profile_dir() -> str:
    """Gets the OS path for the user's real Microsoft Edge profile on Windows."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set. Cannot resolve Edge profile directory.")

    custom_dir = os.getenv("X_REAL_PROFILE_DIR")
    if custom_dir:
        return custom_dir

    return str(Path(local_app_data) / "Microsoft" / "Edge" / "User Data")


def scrape_x_search_playwright(
    query: str,
    limit: int = 500,
    out_csv: str = "tweets_colombia.csv",
    headless: bool = True,
    scroll_pause: float = 1.2,
    max_scrolls: int = 120,
    chunk_size: int = 100,
    debug_dir: str | None = None,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    out_path = Path(out_csv)
    start_time = time.time()

    logger.info("Starting scrape: limit=%s headless=%s max_scrolls=%s browser=msedge", limit, headless, max_scrolls)
    logger.debug("Query: %s", query)

    with sync_playwright() as p:
        browser_args = ["--disable-blink-features=AutomationControlled"]
        user_data_dir = _get_real_profile_dir()
        logger.info("Using real Microsoft Edge profile at: %s", user_data_dir)
        profile_name = os.getenv("X_PROFILE_NAME")
        if profile_name:
            logger.info("Using explicit profile name: %s", profile_name)
            browser_args.append(f"--profile-directory={profile_name}")

        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                locale="es-ES",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                channel="msedge",
                args=browser_args,
            )
        except Exception as e:
            if "SQL" in str(e) or "lock" in str(e).lower() or "Target directory" in str(e):
                raise SystemExit(
                    "\n\nERROR: Playwright cannot access the Microsoft Edge profile because the browser is currently running.\n"
                    "Please CLOSE all Edge windows completely and run the script again.\n\n"
                    f"Original Error: {e}"
                )
            raise e

        logger.info("Checkpoint 1: Edge profile context opened successfully: %s", user_data_dir)

        # Bypass webdriver detection for Chromium-based Edge.
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page = context.pages[0] if context.pages else context.new_page()

        logger.info("Using Edge real profile - login automation disabled.")
        if not headless:
            logger.debug("Giving 3 seconds for existing tabs to restore and settle")
            page.wait_for_timeout(3000)

        search_url = f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"
        page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(int(scroll_pause * 1000))
        try:
            page.wait_for_selector('article[role="article"]', timeout=15_000)
        except Exception as e:
            logger.error("Checkpoint 2 failed: initial tweets not found within 15s.")
            _save_debug(page, debug_dir, "error_carga_inicial")
            raise RuntimeError(
                "Initial search load failed: no tweets found. Verify Edge session or blocking."
            ) from e
        logger.debug("Search URL loaded: %s", page.url)

        last_height = 0
        stagnant_rounds = 0

        for scroll_idx in range(max_scrolls):
            articles = page.locator('article[role="article"]')
            n = articles.count()
            logger.debug("Scroll %s: articles=%s records=%s", scroll_idx + 1, n, len(records))
            if scroll_idx == 0:
                logger.info("Initial articles found: %s", n)

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
                logger.info("Saved chunk: %s records", len(records))

            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(int(scroll_pause * 1000))
            new_height = page.evaluate("document.body.scrollHeight")

            if new_height == last_height:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            last_height = new_height

            if stagnant_rounds >= 4:
                logger.info("Stopping after %s stagnant scrolls", stagnant_rounds)
                break

        if not records:
            logger.warning("No tweets captured; check Edge session and selectors")
            if debug_dir:
                debug_path = Path(debug_dir)
                debug_path.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(debug_path / "empty_results.png"), full_page=True)
                (debug_path / "page.html").write_text(page.content(), encoding="utf-8")
                logger.info("Saved debug artifacts to %s", debug_path.resolve())

        context.close()

    df = pd.DataFrame(records).drop_duplicates(subset=["id"]).head(limit)
    df.to_csv(out_path, index=False)
    elapsed = time.time() - start_time
    logger.info("Dataset saved: %s (%s rows, %.2fs)", out_path.resolve(), len(df), elapsed)
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
    parser.add_argument(
        "--log-level",
        default=os.getenv("X_LOG_LEVEL", "INFO"),
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument(
        "--log-file",
        default=os.getenv("X_LOG_FILE", ""),
        help="Optional log file path",
    )
    parser.add_argument(
        "--debug-dir",
        default=os.getenv("X_DEBUG_DIR", ""),
        help="Directory for debug artifacts (screenshot/html)",
    )
    return parser.parse_args()


def main() -> None:
    if load_dotenv:
        load_dotenv()

    args = _parse_args()
    log_level = args.log_level.upper()
    debug_dir = args.debug_dir or os.getenv("X_DEBUG_DIR", "")
    log_file = args.log_file.strip() or os.getenv("X_LOG_FILE", "").strip()
    if not log_file and debug_dir:
        log_file = str(Path(debug_dir) / "scrape.log")
    _configure_logging(log_level, log_file or None)
    logger.info("Log level: %s", log_level)
    if log_file:
        logger.info("Log file: %s", Path(log_file).resolve())

    headless = args.headless and not args.headful
    scrape_x_search_playwright(
        query=args.query,
        limit=args.limit,
        out_csv=args.out,
        headless=headless,
        scroll_pause=args.scroll_pause,
        max_scrolls=args.max_scrolls,
        chunk_size=args.chunk_size,
        debug_dir=debug_dir or None,
    )


if __name__ == "__main__":
    main()
