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


CATEGORY_SELECTORS = [
    'input[aria-label="Category (required)"]',
    'input[role="combobox"][aria-label*="Category"]',
    'input[aria-label*="Category"]',
    'input[aria-label*="category"]',
]


async def _read_value(field) -> str:
    try:
        return await field.evaluate("el => el.value || ''")
    except Exception:
        return ""


async def enter_category_multi_strategy(page, category: str) -> tuple[bool, object]:
    """Try several strategies to get text into Facebook's category combobox
    and return (success, field_locator). Verifies el.value after each try."""

    field = None
    used_sel = None
    for sel in CATEGORY_SELECTORS:
        try:
            loc = page.locator(sel).first
            count = await loc.count()
            info(f"[Category] selector '{sel}': {count} found")
            if count > 0:
                field = loc
                used_sel = sel
                break
        except Exception as e:
            warn(f"[Category] selector '{sel}' raised: {e}")

    if field is None:
        fail("[Category] No category input found with any selector")
        return False, None

    info(f"[Category] Using field via: {used_sel}")

    async def clear_field():
        try:
            await field.click(timeout=5_000)
            await asyncio.sleep(0.2)
            await page.keyboard.press("Control+a")
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.2)
        except Exception as e:
            warn(f"[Category] clear_field failed: {e}")

    async def strategy_keyboard_type():
        info("[Category] Strategy 1: click + keyboard.type")
        await clear_field()
        await page.keyboard.type(category, delay=100)
        await asyncio.sleep(0.5)

    async def strategy_press_sequentially():
        info("[Category] Strategy 2: locator.press_sequentially")
        await clear_field()
        try:
            await field.press_sequentially(category, delay=100)
        except Exception as e:
            warn(f"[Category] press_sequentially unavailable/failed: {e}")
        await asyncio.sleep(0.5)

    async def strategy_native_setter():
        info("[Category] Strategy 3: native value setter + input/change events")
        try:
            await field.click(timeout=5_000)
        except Exception:
            pass
        await page.evaluate(
            """([el, text]) => {
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(el, '');
                el.dispatchEvent(new Event('input', { bubbles: true }));
                setter.call(el, text);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            [await field.element_handle(), category],
        )
        await asyncio.sleep(0.5)

    async def strategy_exec_command():
        info("[Category] Strategy 4: focus + execCommand insertText")
        await clear_field()
        await page.evaluate(
            """([el, text]) => {
                el.focus();
                document.execCommand('insertText', false, text);
            }""",
            [await field.element_handle(), category],
        )
        await asyncio.sleep(0.5)

    async def strategy_char_by_char_press():
        info("[Category] Strategy 5: per-character keyboard.press")
        await clear_field()
        for ch in category:
            try:
                await page.keyboard.press(ch if ch != " " else "Space")
            except Exception:
                await page.keyboard.type(ch)
            await asyncio.sleep(0.06)
        await asyncio.sleep(0.5)

    strategies = [
        strategy_keyboard_type,
        strategy_press_sequentially,
        strategy_native_setter,
        strategy_exec_command,
        strategy_char_by_char_press,
    ]

    for i, strat in enumerate(strategies, 1):
        try:
            await strat()
        except Exception as e:
            warn(f"[Category] strategy {i} raised: {e}")
            continue
        val = await _read_value(field)
        info(f"[Category] value after strategy {i}: {val!r}")
        if val.strip():
            ok(f"[Category] Successfully entered text via strategy {i}")
            return True, field
        else:
            warn(f"[Category] Strategy {i} left field empty — trying next")

    fail("[Category] All 5 strategies failed to put text into the field")
    return False, field


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

    # ── Network diagnostics ─────────────────────────────────────────────────
    # The previous run showed "Create Page" click registering but the button
    # then spinning forever with no success/error UI. That's invisible in the
    # DOM — the only way to see what's really happening is to watch the
    # actual network calls Facebook makes when the button is clicked.
    network_log = []

    def on_request(req):
        if any(k in req.url for k in ["pages/creation", "graphql", "api/graphql", "CometPage"]):
            network_log.append(f"[REQ ] {req.method} {req.url[:180]}")

    def on_response(resp):
        if any(k in resp.url for k in ["pages/creation", "graphql", "api/graphql", "CometPage"]):
            network_log.append(f"[RESP] {resp.status} {resp.url[:180]}")

    def on_requestfailed(req):
        if any(k in req.url for k in ["pages/creation", "graphql", "api/graphql", "CometPage"]):
            failure = req.failure
            network_log.append(f"[FAIL] {req.method} {req.url[:180]} — {failure}")

    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_requestfailed)

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
    # NOTE: Facebook's actual DOM uses aria-label="Category (required)"
    # (confirmed from HTML dump) and is a controlled React combobox, so
    # plain .fill() silently fails. enter_category_multi_strategy() tries
    # 5 different input methods and verifies el.value after each one.
    step("Filling Page category field")
    cat_field_ok, cat_field = await enter_category_multi_strategy(page, category)

    await save_screenshot(page, "05_after_category_type")
    await dump_html(page, "05_after_category_type.html")

    if cat_field_ok:
        info("Waiting for category dropdown options to render")
        options_appeared = False
        for elapsed in range(0, 8):
            for probe_sel in [
                '[role="listbox"]', '[role="option"]',
                'ul[role="listbox"] li', 'div[role="option"]',
                'div[aria-expanded="true"]',
            ]:
                try:
                    if await page.locator(probe_sel).count() > 0:
                        options_appeared = True
                        info(f"Dropdown detected via '{probe_sel}' after {elapsed}s")
                        break
                except Exception:
                    pass
            if options_appeared:
                break
            await asyncio.sleep(1)

        await save_screenshot(page, "05b_dropdown_state")
        await dump_html(page, "05b_dropdown_state.html")

        if not options_appeared:
            warn("No dropdown options detected in DOM after 8s — will still try clicking / keyboard fallback")

        picked = await try_click_text_option(page, category, "Category option")

        if not picked:
            warn(f"No option matched '{category}' text — trying broader option-role click")
            for generic_sel in ['[role="option"]', 'div[role="option"]', 'li[role="option"]']:
                try:
                    opt = page.locator(generic_sel).first
                    if await opt.count() > 0:
                        await opt.click(timeout=5_000, force=True)
                        ok(f"Clicked first available option via '{generic_sel}'")
                        picked = True
                        break
                except Exception as e:
                    warn(f"Generic option click '{generic_sel}' failed: {e}")

        if not picked:
            warn("Still no option clicked — trying ArrowDown+Enter keyboard select")
            try:
                if cat_field is not None:
                    await cat_field.click(timeout=5_000)
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.5)
                await page.keyboard.press("Enter")
                ok("Pressed ArrowDown+Enter to accept first suggestion")
                picked = True
            except Exception as e:
                warn(f"Keyboard fallback failed: {e}")

        if not picked:
            fail("Could not select ANY category option — Create Page button will likely stay disabled")
    else:
        warn("Could not fill category field with any strategy — dumping HTML for inspection")
        await dump_html(page, "05_no_category_field.html")

    await save_screenshot(page, "06_after_category_select")
    await dump_html(page, "06_after_category_select.html")

    # ── Step 5: Click "Create Page" ONCE, then watch what actually happens ─
    step("Clicking Create Page and watching the real network response")

    DONE_SELECTORS = [
        'span:has-text("Your Page is ready")',
        'span:has-text("Page created")',
        'div:has-text("Your Page was created")',
        'span:has-text("was created")',
    ]

    ERROR_TEXT_SNIPPETS = [
        "something went wrong", "try again later", "please try again",
        "temporarily blocked", "temporarily restricted", "unusual activity",
        "we restrict certain content", "verify your identity",
        "confirm your identity", "action blocked", "couldn't create",
        "could not create", "limit", "not available right now",
    ]

    async def is_done() -> bool:
        for sel in DONE_SELECTORS:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        if "/pages/creation" not in page.url and "pages/" in page.url:
            return True
        return False

    async def find_error_text() -> str | None:
        try:
            body_text = (await page.locator("body").inner_text()).lower()
        except Exception:
            return None
        for snippet in ERROR_TEXT_SNIPPETS:
            if snippet in body_text:
                return snippet
        return None

    async def button_is_spinning(sel: str) -> bool:
        """Detect a disabled/aria-busy button or one containing a spinner svg."""
        try:
            btn = page.locator(sel).last
            if await btn.count() == 0:
                return False
            disabled = await btn.get_attribute("aria-disabled")
            busy = await btn.get_attribute("aria-busy")
            has_spinner = await btn.evaluate(
                "el => !!el.querySelector('svg, [role=\"progressbar\"], [class*=\"spinner\" i]')"
            )
            return disabled == "true" or busy == "true" or has_spinner
        except Exception:
            return False

    NEXT_LABELS = ["Create Page", "Create page", "Next", "Done", "Save", "Continue", "Finish"]
    CREATE_BTN_SELECTORS = [
        'div[aria-label="Create Page"][role="button"]',
        'div[role="button"]:text-is("Create Page")',
    ]

    finished = False

    if await is_done():
        ok("Detected completion before any click — page already created")
        finished = True
    else:
        clicked, which = await find_and_click_button(page, NEXT_LABELS)
        await save_screenshot(page, "07_immediately_after_click")
        await dump_html(page, "07_immediately_after_click.html")

        if not clicked:
            fail("Could not find/click Create Page button at all")
        else:
            info(f"Clicked '{which}' — now polling for up to 90s instead of re-clicking")
            info("(Re-clicking a submitting button can trigger duplicate/conflicting "
                 "requests, so we only click once and then observe.)")

            for elapsed in range(0, 90, 5):
                await asyncio.sleep(5)
                url_now = page.url
                spinning = False
                for sel in CREATE_BTN_SELECTORS:
                    if await button_is_spinning(sel):
                        spinning = True
                        break

                err = await find_error_text()
                info(f"[{elapsed+5}s] URL={url_now}  spinning={spinning}  error_text={err!r}")

                if elapsed % 20 == 0:
                    await save_screenshot(page, f"07_watch_{elapsed+5}s")

                if await is_done():
                    ok(f"Detected completion after {elapsed+5}s")
                    finished = True
                    break

                if err:
                    fail(f"Facebook showed an error message: '{err}'")
                    await save_screenshot(page, "FAIL_error_message")
                    await dump_html(page, "FAIL_error_message.html")
                    break

                if not spinning and elapsed >= 10:
                    # Button stopped spinning but we're not "done" — something
                    # resolved (maybe silently). Give it one more short look.
                    info("Spinner cleared without a recognized success state — checking once more")
                    await asyncio.sleep(3)
                    if await is_done():
                        ok("Detected completion on final check")
                        finished = True
                    break

            if not finished:
                warn(f"Still not confirmed done after {elapsed+5}s of polling")

    if network_log:
        step("Network activity captured during Create Page flow")
        for line in network_log[-40:]:   # last 40 entries, most relevant
            info(line)
    else:
        warn("No matching network requests captured (graphql/pages-creation) — "
             "the button click may not have actually fired a request at all")


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
