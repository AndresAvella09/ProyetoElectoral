"""Playwright-based X/Twitter search scraper.

This script runs outside Jupyter to avoid asyncio/subprocess conflicts on Windows.
It saves results to CSV and supports login via username/password or manual headful login.
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


def _click_first(page, selectors: list[str]) -> bool:
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            loc.first.click()
            return True
    return False


def _login_with_credentials(page, debug_dir: str | None) -> bool:
    username = os.getenv("X_USERNAME", "").strip() or os.getenv("X_EMAIL", "").strip()
    password = os.getenv("X_PASSWORD", "").strip()
    login_hint = (
        os.getenv("X_LOGIN_HINT", "").strip()
        or os.getenv("X_EMAIL", "").strip()
        or os.getenv("X_USERNAME", "").strip()
    )

    if not username or not password:
        return False

    logger.info("Attempting credential login")
    page.goto("https://x.com/", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2000)
    page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2000)

    try:
        if page.locator("text=Accept all cookies").count() > 0:
            page.locator("text=Accept all cookies").first.click()
        elif page.locator("text=Aceptar todas las cookies").count() > 0:
            page.locator("text=Aceptar todas las cookies").first.click()
    except Exception as e:
        logger.debug(f"Could not accept cookies banner: {e}")

    try:
        page.wait_for_selector('input[name="text"], input[name="username"]', timeout=10_000)
    except Exception:
        logger.warning("Timeout waiting for login input")
        _save_debug(page, debug_dir, "login_input_timeout")
        return False

    text_input = page.locator('input[name="text"]')
    if text_input.count() == 0:
        text_input = page.locator('input[autocomplete="username"]')
    if text_input.count() == 0:
        logger.warning("Login input selector not found after wait")
        _save_debug(page, debug_dir, "login_input_empty")
        return False

    logger.debug("Found username input. Trying to fill.")
    text_input.first.click()
    page.wait_for_timeout(500)
    text_input.first.fill(username)
    page.wait_for_timeout(500)
    _save_debug(page, debug_dir, "post_fill_username")
    
    # Try finding the "Next" / "Siguiente" button specifically
    next_buttons = page.locator('button:has-text("Siguiente"), button:has-text("Next")')
    if next_buttons.count() > 0:
        logger.debug(f"Clicking NEXT button via localized text. Found {next_buttons.count()} buttons.")
        next_buttons.first.click(force=True)
    else:
        logger.debug("Pressing Enter as fallback for NEXT.")
        text_input.first.press("Enter")
        
    page.wait_for_timeout(3000)
    _save_debug(page, debug_dir, "post_click_username")

    # Some accounts are asked to re-enter username/email/phone
    if page.locator('input[name="password"]').count() == 0 and page.locator('input[name="text"]').count() > 0:
        logger.debug("Still on a text input page. Checking if need to enter hint.")
        if login_hint:
            page.locator('input[name="text"]').first.type(login_hint, delay=50)
            page.wait_for_timeout(500)
            
            hint_next = page.locator('button:has-text("Siguiente"), button:has-text("Next")')
            if hint_next.count() > 0:
                hint_next.first.click()
            else:
                page.locator('input[name="text"]').first.press("Enter")
            page.wait_for_timeout(3000)
        else:
            logger.debug("No login_hint provided but asked for text input")

    pwd = page.locator('input[name="password"]')
    if pwd.count() == 0:
        try:
            # Maybe the transition taking a bit longer
            page.wait_for_selector('input[name="password"]', timeout=10_000)
        except Exception:
            logger.warning("Password input not found; login flow may require extra steps")
            _save_debug(page, debug_dir, "password_missing")
            return False
        pwd = page.locator('input[name="password"]')

    pwd.first.fill(password)
    page.keyboard.press("Enter")

    try:
        page.wait_for_url("https://x.com/home", timeout=30_000)
    except Exception:
        logger.warning("Login did not redirect to home; continuing anyway")
        _save_debug(page, debug_dir, "login_no_redirect")

    page.wait_for_timeout(1200)
    return True


def _wait_for_manual_login(page) -> bool:
    page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=90_000)
    logger.info("Waiting for manual login in the opened browser... (timeout 3 mins)")
    try:
        page.wait_for_url("https://x.com/home", timeout=180_000)
    except Exception:
        logger.warning("Manual login timed out")
        return False
    return True


def _get_real_profile_dir(browser_name: str) -> str:
    """Gets the OS path for the user's real browser profile. Only for Windows edge/chrome."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("Could not find LOCALAPPDATA environment variable.")

    custom_dir = os.getenv("X_REAL_PROFILE_DIR")
    if custom_dir:
        return custom_dir

    if browser_name == "msedge":
        return str(Path(local_app_data) / "Microsoft" / "Edge" / "User Data")
    elif browser_name == "chromium":
        return str(Path(local_app_data) / "Google" / "Chrome" / "User Data")
    else:
        raise ValueError(f"--use-real-profile only supports msedge or chromium. Got: {browser_name}")

def scrape_x_search_playwright(
    query: str,
    limit: int = 500,
    out_csv: str = "tweets_colombia.csv",
    headless: bool = True,
    scroll_pause: float = 1.2,
    max_scrolls: int = 120,
    chunk_size: int = 100,
    debug_dir: str | None = None,
    browser_name: str = "chromium",
    use_real_profile: bool = False,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    out_path = Path(out_csv)
    start_time = time.time()

    logger.info("Starting scrape: limit=%s headless=%s max_scrolls=%s browser=%s", limit, headless, max_scrolls, browser_name)
    logger.debug("Query: %s", query)

    with sync_playwright() as p:
        browser_args = []
        if browser_name in ("chromium", "msedge"):
            browser_args = ["--disable-blink-features=AutomationControlled"]

        if browser_name == "chromium":
            browser_type = p.chromium
            launch_kwargs = {"args": browser_args}
        elif browser_name == "msedge":
            browser_type = p.chromium
            launch_kwargs = {"channel": "msedge", "args": browser_args}
        elif browser_name == "firefox":
            browser_type = p.firefox
            launch_kwargs = {}
        elif browser_name == "webkit":
            browser_type = p.webkit
            launch_kwargs = {}
        else:
            raise ValueError(f"Unsupported browser: {browser_name}")

        if use_real_profile:
            user_data_dir = _get_real_profile_dir(browser_name)
            logger.info("Using real browser profile at: %s", user_data_dir)
            profile_name = os.getenv("X_PROFILE_NAME")
            if profile_name:
                logger.info("Using explicit profile name: %s", profile_name)
                # It's an array for launch arguments
                launch_kwargs.setdefault("args", []).append(f"--profile-directory={profile_name}")
        else:
            user_data_dir = f"x_profile_{browser_name}"

        try:
            context = browser_type.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                locale="es-ES",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                **launch_kwargs,
            )
        except Exception as e:
            if use_real_profile and ("SQL" in str(e) or "lock" in str(e).lower() or "Target directory" in str(e)):
                raise SystemExit(
                    f"\n\nERROR: Playwright cannot access the {browser_name} profile because the browser is currently running.\n"
                    f"Please CLOSE all {browser_name} windows completely and run the script again.\n\n"
                    f"Original Error: {e}"
                )
            raise e
        
        # Bypass webdriver detection only for Chromium-based browsers
        if browser_name in ("chromium", "msedge"):
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page = context.pages[0] if context.pages else context.new_page()
        
        if use_real_profile:
            logger.info("Using real profile - skipping authentication checks completely.")
            logger.info("Assuming user is already logged into X in their personal browser.")
            # Added a small pause to allow user to close default restored tabs or popups
            if not headless:
                logger.debug("Giving 3 seconds for existing tabs to restore and settle")
                page.wait_for_timeout(3000)
        else:
            # Check if already logged in via persistent profile
            logger.info("Checking persistent session state...")
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(3000)

            if "home" not in page.url or page.locator('a[data-testid="login"]').count() > 0:
                logger.info("Not currently logged in. Checking manual vs credential flow.")
                wait_flag = os.getenv("X_WAIT_FOR_LOGIN", "").strip().lower()
                if wait_flag in ("1", "true", "yes"):
                    logger.info("X_WAIT_FOR_LOGIN is active. Please log in manually on the pop-up browser.")
                    manual_ok = _wait_for_manual_login(page)
                    logger.info("Manual login: %s", manual_ok)
                else:
                    logged_in = _login_with_credentials(page, debug_dir)
                    if not logged_in:
                        logger.warning("Credential login failed. Check logs or use X_WAIT_FOR_LOGIN=1.")
            else:
                logger.info("Already logged in via persistent profile!")

        search_url = f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"
        page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(int(scroll_pause * 1000))
        logger.debug("Search URL loaded: %s", page.url)

        last_height = 0
        stagnant_rounds = 0

        for scroll_idx in range(max_scrolls):
            articles = page.locator('article[role="article"]')
            n = articles.count()
            if scroll_idx == 0:
                logger.info("Initial articles found: %s", n)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Scroll %s: articles=%s records=%s", scroll_idx + 1, n, len(records))

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
            logger.warning("No tweets captured; check login and selectors")
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
    parser.add_argument(
        "--browser",
        default="chromium",
        choices=["chromium", "firefox", "webkit", "msedge"],
        help="Browser to use for Playwright",
    )
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
    parser.add_argument(
        "--use-real-profile",
        action="store_true",
        help="Use real browser profile from LOCALAPPDATA instead of local x_profile. Resolves bot detection (Edge/Chrome only). Make sure browser is closed before running.",
    )
    return parser.parse_args()


def main() -> None:
    if load_dotenv:
        load_dotenv()

    username = os.getenv("X_USERNAME", "").strip() or os.getenv("X_EMAIL", "").strip()
    password = os.getenv("X_PASSWORD", "").strip()
    wait_flag = os.getenv("X_WAIT_FOR_LOGIN", "").strip().lower() in ("1", "true", "yes")

    if not wait_flag and (not username or not password):
        raise SystemExit(
            "Missing credentials. Set X_USERNAME and X_PASSWORD in .env, "
            "or set X_WAIT_FOR_LOGIN=1 to login manually in headful mode."
        )

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
        browser_name=args.browser,
        use_real_profile=args.use_real_profile,
    )


if __name__ == "__main__":
    main()
