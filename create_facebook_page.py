"""
create_facebook_page.py — VERBOSE DEBUG VERSION
─────────────────────────────────────────────────
Creates a Facebook Page named "Live Chef" with category "Food",
using an existing storage_state.json / FB_STORAGE_STATE session.

Every step prints exactly what it's doing and why it failed, and saves
a screenshot + HTML dump at each stage so failures are diagnosable
from GitHub Actions artifacts.

Run with:  python -u create_facebook_page.py
Env vars:
    FB_STORAGE_STATE   - JSON string of Playwright storage state (cookies)
    PAGE_NAME          - defaults to "Live Chef"
    PAGE_CATEGORY      - defaults to "Food"
"""

import asyncio, json, os, sys
from pathlib import Path
from datetime import datetime
import functools

print = functools.partial(print, flush=True)

from playwright.async_api import async_playwright

# ─────────────────────────────────────────────────────────────────────────────
STORAGE_STATE      = "storage_state.json"
FB_STORAGE_STATE_ENV = "FB_STORAGE_STATE"
SCREENSHOTS_DIR    = Path("screenshots")
PAGE_NAME          = os.environ.get("PAGE_NAME", "Live Chef")
PAGE_CATEGORY      = os.environ.get("PAGE_CATEGORY", "Food")

# ─────────────────────────────────────────────────────────────────────────────
# STEP LOGGER
# ─────────────────────────────────────────────────────────────────────────────
_step = 0
def step(msg):
    global _step
    _step += 1
    print(f"\n{'='*60}")
    print(f"  STEP {_step}: {msg}")
    print(f"{'='*60}")

def info(msg):   print(f"   ℹ️  {msg}")
def ok(msg):     print(f"   ✅ {msg}")
def warn(msg):   print(f"   ⚠️  {msg}")
def fail(msg):   print(f"   ❌ {msg}")


async def save_screenshot(page, name: str):
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    for p in [SCREENSHOTS_DIR / f"{name}.png", Path(f"{name}.png")]:
        try:
            await page.screenshot(path=str(p), full_page=False)
            info(f"Screenshot saved: {p}")
        except Exception as e:
            warn(f"Screenshot failed {p}: {e}")


async def dump_html(page, filename: str):
    try:
        content = await page.content()
        Path(filename).write_text(content, encoding="utf-8")
        info(f"HTML dumped: {filename} ({len(content)} chars)")
    except Exception as e:
        warn(f"HTML dump failed: {e}")


def resolve_fb_storage_state() -> str | None:
    step("Resolving Facebook storage state")
    env_val = os.environ.get(FB_STORAGE_STATE_ENV)
    if env_val:
        info(f"FB_STORAGE_STATE env var found, length={len(env_val)}")
        try:
            parsed = json.loads(env_val)
            cookies = parsed.get("cookies", [])
            ok(f"Valid JSON — {len(cookies)} cookies found")
            return env_val
        except json.JSONDecodeError as e:
            fail(f"FB_STORAGE_STATE is not valid JSON: {e}")
    else:
        warn("FB_STORAGE_STATE env var not set")

    if Path(STORAGE_STATE).exists():
        info(f"Found local {STORAGE_STATE} — using it")
        return Path(STORAGE_STATE).read_text(encoding="utf-8")

    fail("No valid Facebook session found!")
    return None


def classify_url(url: str) -> str:
    if "checkpoint" in url:                 return "CHECKPOINT"
    if "/login" in url and "caa" not in url: return "LOGIN_WALL"
    if "pages/create" in url:               return "PAGE_CREATE"
    if "pages/" in url:                     return "PAGE_VIEW"
    if "facebook.com" in url:               return "FACEBOOK_PAGE"
    return "OTHER"


FEED_SELECTORS = [
    '[aria-label="Home"]', '[data-pagelet="LeftRail"]', 'div[role="feed"]',
    '[aria-label="Create"]', 'div[role="main"]',
]


async def ensure_logged_in(page) -> bool:
    step("Checking Facebook login state")
    for attempt in range(6):
        url = page.url
        url_type = classify_url(url)
        info(f"Attempt {attempt+1}/6 — URL: {url}  (type={url_type})")

        if url_type == "CHECKPOINT":
            fail("Account checkpoint/restriction detected — manual action required")
            await save_screenshot(page, f"LOGIN_CHECKPOINT_{attempt+1}")
            return False

        if url_type == "LOGIN_WALL":
            fail("Hard login wall — session cookies are EXPIRED")
            await save_screenshot(page, f"LOGIN_WALL_{attempt+1}")
            return False

        for sel in FEED_SELECTORS:
            try:
                if await page.locator(sel).count() > 0:
                    ok(f"Logged in confirmed via: {sel}")
                    return True
            except Exception:
                pass

        info(f"Feed not ready yet — waiting 3s (attempt {attempt+1}/6)")
        await asyncio.sleep(3)

    fail("Login check exhausted all 6 attempts")
    await dump_html(page, "login_failed_final.html")
    await save_screenshot(page, "LOGIN_FAILED_FINAL")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers for generic "find & fill" / "find & click"
# ─────────────────────────────────────────────────────────────────────────────

async def try_fill(page, selectors: list[str], text: str, label: str) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            count = await loc.count()
            info(f"[{label}] selector '{sel}': {count} found")
            if count == 0:
                continue
            await loc.scroll_into_view_if_needed(timeout=5_000)
            await loc.click(timeout=5_000)
            await asyncio.sleep(0.3)
            await loc.fill("")
            await loc.fill(text)
            await asyncio.sleep(0.3)
            val = await loc.input_value() if await loc.evaluate("el => el.tagName") == "INPUT" else None
            ok(f"[{label}] filled via '{sel}'" + (f" (value={val!r})" if val else ""))
            return True
        except Exception as e:
            warn(f"[{label}] '{sel}' failed: {e}")
    return False


async def try_click_text_option(page, text: str, label: str) -> bool:
    """Click a dropdown/list option or button matching visible text (case-insensitive substring)."""
    selectors = [
        f'div[role="option"]:has-text("{text}")',
        f'li:has-text("{text}")',
        f'span:text-is("{text}")',
        f'div[role="button"]:has-text("{text}")',
        f'text="{text}"',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            count = await loc.count()
            info(f"[{label}] option selector '{sel}': {count} found")
            if count == 0:
                continue
            await loc.scroll_into_view_if_needed(timeout=5_000)
            await loc.click(timeout=5_000, force=True)
            ok(f"[{label}] clicked option via '{sel}'")
            return True
        except Exception as e:
            warn(f"[{label}] option '{sel}' failed: {e}")

    # JS fallback: find any element whose text matches
    try:
        hit = await page.evaluate(
            """(text) => {
                const els = Array.from(document.querySelectorAll(
                    'div[role="option"],li,span,div[role="button"],button'
                ));
                const t = text.toLowerCase();
                const el = els.find(e => (e.textContent||'').trim().toLowerCase() === t
                                       || (e.textContent||'').trim().toLowerCase().includes(t));
                if (!el) return null;
                el.click();
                return el.outerHTML.slice(0, 150);
            }""",
            text,
        )
        if hit:
            ok(f"[{label}] JS fallback clicked: {hit}")
            return True
    except Exception as e:
        warn(f"[{label}] JS fallback failed: {e}")

    return False


async def find_and_click_button(page, labels: list[str]) -> tuple[bool, str]:
    """Try to click a button/div[role=button] matching any of the given labels."""
    for label_text in labels:
        selectors = [
            f'div[aria-label="{label_text}"][role="button"]',
            f'div[role="button"]:text-is("{label_text}")',
            f'span:text-is("{label_text}")',
            f'div[role="button"]:has-text("{label_text}")',
            f'button:has-text("{label_text}")',
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).last
                count = await btn.count()
                if count == 0:
                    continue
                disabled = await btn.get_attribute("aria-disabled")
                if disabled == "true":
                    info(f"Button '{label_text}' via '{sel}' is disabled — skipping")
                    continue
                await btn.scroll_into_view_if_needed(timeout=5_000)
                await btn.click(timeout=8_000, force=True)
                ok(f"Clicked '{label_text}' via '{sel}'")
                return True, label_text
            except Exception as e:
                warn(f"Click '{label_text}' via '{sel}' failed: {e}")
    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# Main page-creation flow
# ─────────────────────────────────────────────────────────────────────────────

async def create_page(page_name: str, category: str) -> bool:
    step("Starting Facebook Page creation flow")
    info(f"Page name : {page_name}")
    info(f"Category  : {category}")

    async with async_playwright() as p:
        step("Launching Chromium browser")
        try:
            browser = await p.chromium.launch(
                headless=True,
                timeout=30_000,
                args=[
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars", "--disable-dev-shm-usage",
                ],
            )
            ok("Browser launched")
        except Exception as e:
            fail(f"Browser launch FAILED: {e}")
            return False

        storage_state_json = resolve_fb_storage_state()
        if not storage_state_json:
            fail("No Facebook session available — aborting")
            await browser.close()
            return False

        step("Creating browser context with session cookies")
        try:
            state = json.loads(storage_state_json)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="Asia/Karachi",
                storage_state=state,
            )
            ok(f"Context created with {len(state.get('cookies', []))} cookies")
        except Exception as e:
            fail(f"Context creation failed: {e}")
            await browser.close()
            return False

        created = False
        try:
            created = await _run_create_flow(context, page_name, category)
        except Exception as e:
            fail(f"Page creation flow crashed: {e}")
            import traceback
            print(traceback.format_exc())
        finally:
            try:
                fresh = await context.storage_state()
                Path(STORAGE_STATE).write_text(json.dumps(fresh), encoding="utf-8")
                ok(f"Saved refreshed storage_state ({len(fresh.get('cookies', []))} cookies)")
            except Exception as e:
                warn(f"Could not save storage_state: {e}")
            await browser.close()
            ok("Browser closed")

    return created


async def _run_create_flow(context, page_name: str, category: str) -> bool:
    page = await context.new_page()

    # ── Step 1: Load Facebook home, confirm login ──────────────────────────
    step("Loading Facebook homepage")
    try:
        resp = await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60_000)
        info(f"HTTP status: {resp.status if resp else 'unknown'}")
    except Exception as e:
        fail(f"Page load failed: {e}")
        await save_screenshot(page, "FAIL_01_load")
        return False

    await asyncio.sleep(6)
    info(f"Current URL: {page.url}  (type={classify_url(page.url)})")
    await save_screenshot(page, "01_after_load")

    if not await ensure_logged_in(page):
        fail("ABORT: Could not confirm login")
        return False
    ok("Login confirmed")
    await save_screenshot(page, "02_logged_in")

    # ── Step 2: Navigate to Page creation ──────────────────────────────────
    step("Navigating to Page creation URL")
    try:
        resp = await page.goto("https://www.facebook.com/pages/creation/",
                                wait_until="domcontentloaded", timeout=60_000)
        info(f"HTTP status: {resp.status if resp else 'unknown'}")
    except Exception as e:
        fail(f"Navigation to pages/creation failed: {e}")
        await save_screenshot(page, "FAIL_02_nav")
        return False

    await asyncio.sleep(6)
    info(f"Current URL: {page.url}  (type={classify_url(page.url)})")
    await save_screenshot(page, "03_pages_creation")
    await dump_html(page, "03_pages_creation.html")

    # ── Step 3: Fill Page name ─────────────────────────────────────────────
    step("Filling Page name field")
    NAME_SELECTORS = [
        'input[aria-label="Page name"]',
        'input[placeholder*="Page name"]',
        'input[aria-label*="name"]',
        'input[type="text"]',
    ]
    name_ok = await try_fill(page, NAME_SELECTORS, page_name, "Page name")
    await save_screenshot(page, "04_after_name_fill")
    if not name_ok:
        warn("Could not fill Page name automatically — dumping HTML for inspection")
        await dump_html(page, "04_no_name_field.html")

    # ── Step 4: Fill / select Category ─────────────────────────────────────
    step("Filling Page category field")
    CATEGORY_INPUT_SELECTORS = [
        'input[aria-label="Category"]',
        'input[placeholder*="Category"]',
        'input[aria-label*="category"]',
    ]
    cat_field_ok = await try_fill(page, CATEGORY_INPUT_SELECTORS, category, "Category")
    await save_screenshot(page, "05_after_category_type")

    if cat_field_ok:
        # wait for the dropdown options to render, then click the "Food" option
        info("Waiting for category dropdown options to appear")
        await asyncio.sleep(2)
        picked = await try_click_text_option(page, category, "Category option")
        if not picked:
            warn(f"Could not click a dropdown option matching '{category}' — trying Enter key")
            try:
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.3)
                await page.keyboard.press("Enter")
                ok("Pressed ArrowDown+Enter to accept first suggestion")
            except Exception as e:
                warn(f"Keyboard fallback failed: {e}")
    else:
        warn("Could not find a category input field — dumping HTML for inspection")
        await dump_html(page, "05_no_category_field.html")

    await save_screenshot(page, "06_after_category_select")
    await dump_html(page, "06_after_category_select.html")

    # ── Step 5: Click "Next" repeatedly until page is created ─────────────
    step("Clicking Next / Create Page repeatedly until finished")

    DONE_SELECTORS = [
        'span:has-text("Your Page is ready")',
        'span:has-text("Page created")',
        'div:has-text("Your Page was created")',
        'span:has-text("was created")',
    ]

    async def is_done() -> bool:
        for sel in DONE_SELECTORS:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        # Also treat navigation to a real page id URL as success
        if "/pages/creation" not in page.url and "pages/" in page.url:
            return True
        return False

    NEXT_LABELS = ["Next", "Create Page", "Create page", "Done", "Save", "Continue", "Finish"]

    max_clicks = 8
    finished = False
    for attempt in range(1, max_clicks + 1):
        info(f"Next-loop attempt {attempt}/{max_clicks} — URL: {page.url}")

        if await is_done():
            ok(f"Detected completion before click {attempt}")
            finished = True
            break

        clicked, which = await find_and_click_button(page, NEXT_LABELS)
        await save_screenshot(page, f"07_next_click_{attempt}")
        await dump_html(page, f"07_next_click_{attempt}.html")

        if not clicked:
            warn(f"No clickable Next/Create button found on attempt {attempt}")
            # give any lazy-loaded UI a moment, then try once more
            await asyncio.sleep(3)
            clicked, which = await find_and_click_button(page, NEXT_LABELS)
            if not clicked:
                warn("Still no button found — stopping loop")
                break

        info(f"Clicked '{which}' on attempt {attempt} — waiting for UI to update")
        await asyncio.sleep(4)
        info(f"URL after click: {page.url}  (type={classify_url(page.url)})")

        if await is_done():
            ok(f"Detected completion after click {attempt}")
            finished = True
            break

    await save_screenshot(page, "08_final_state")
    await dump_html(page, "08_final_state.html")
    info(f"Final URL: {page.url}")

    if finished:
        ok(f"🎉 PAGE '{page_name}' CREATED SUCCESSFULLY (category: {category})")
    else:
        warn("Could not confirm Page creation completed — check 08_final_state.png/html")
        warn("The Page may still have been created; check your Facebook Pages list manually")

    return finished


# ─────────────────────────────────────────────────────────────────────────────
def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  🚀 Facebook Page creation run started at {ts}")
    print(f"  Python: {sys.version}")
    print(f"  PID: {os.getpid()}")
    print(f"{'='*60}")

    step("Checking environment variables")
    val = os.environ.get(FB_STORAGE_STATE_ENV, "")
    info(f"{FB_STORAGE_STATE_ENV}: {'SET (' + str(len(val)) + ' chars)' if val else 'NOT SET'}")
    info(f"PAGE_NAME: {PAGE_NAME}")
    info(f"PAGE_CATEGORY: {PAGE_CATEGORY}")

    result = asyncio.run(create_page(PAGE_NAME, PAGE_CATEGORY))

    print(f"\n{'='*60}")
    print(f"  Run complete. PageCreated={result}")
    print(f"{'='*60}\n")

    if not result:
        sys.exit(1)


if __name__ == "__main__":
    main()
