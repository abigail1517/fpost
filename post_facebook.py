# ── Step 6: Enter caption ─────────────────────────────────────────────
    step("Entering caption text")
    info(f"Caption to type ({len(caption)} chars): {caption[:80]}")

    async def enter_caption_lexical(page, caption: str) -> bool:
        LEXICAL_SELECTORS = [
            'div[data-lexical-editor="true"][contenteditable="true"]',
            'div[contenteditable="true"][aria-placeholder="Describe your reel..."]',
            'div[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"]',
        ]

        async def strategy_clipboard(field):
            info("Strategy 1: clipboard paste via Ctrl+V")
            await field.click(timeout=5_000)
            await asyncio.sleep(0.4)
            await page.keyboard.press("Control+a")
            await asyncio.sleep(0.2)
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.2)
            await page.evaluate(
                "(text) => navigator.clipboard.writeText(text).catch(() => {})",
                caption,
            )
            await asyncio.sleep(0.3)
            await page.keyboard.press("Control+v")
            await asyncio.sleep(0.8)

        async def strategy_exec_command(field):
            info("Strategy 2: execCommand insertText")
            await field.click(timeout=5_000)
            await asyncio.sleep(0.3)
            await page.evaluate(
                """(el, text) => {
                    el.focus();
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                    document.execCommand('insertText', false, text);
                }""",
                [field, caption],
            )
            await asyncio.sleep(0.5)

        async def strategy_input_event(field):
            info("Strategy 3: InputEvent dispatch")
            await field.click(timeout=5_000)
            await asyncio.sleep(0.3)
            await page.evaluate(
                """(el, text) => {
                    el.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    sel.removeAllRanges();
                    sel.addRange(range);
                    const ev = new InputEvent('beforeinput', {
                        inputType: 'insertText',
                        data: text,
                        bubbles: true,
                        cancelable: true,
                    });
                    el.dispatchEvent(ev);
                    const ev2 = new InputEvent('input', {
                        inputType: 'insertText',
                        data: text,
                        bubbles: true,
                    });
                    el.dispatchEvent(ev2);
                }""",
                [field, caption],
            )
            await asyncio.sleep(0.5)

        async def strategy_keyboard_type(field):
            info("Strategy 4: keyboard.type fallback")
            await field.click(timeout=5_000)
            await asyncio.sleep(0.3)
            await page.keyboard.press("Control+a")
            await asyncio.sleep(0.2)
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.2)
            await page.keyboard.type(caption, delay=20)
            await asyncio.sleep(0.5)

        strategies = [
            strategy_clipboard,
            strategy_exec_command,
            strategy_input_event,
            strategy_keyboard_type,
        ]

        for i, strategy in enumerate(strategies, 1):
            for sel in LEXICAL_SELECTORS:
                try:
                    field = page.locator(sel).first
                    if await field.count() == 0:
                        continue
                    await strategy(field)
                    txt = await field.evaluate(
                        "el => (el.innerText || el.textContent || '').trim()"
                    )
                    if txt and len(txt) > 2:
                        ok(f"Caption entered via strategy {i} / selector '{sel}' ({len(txt)} chars)")
                        return True
                    else:
                        warn(f"Strategy {i} / '{sel}': field empty after attempt")
                except Exception as e:
                    warn(f"Strategy {i} / '{sel}' raised: {e}")

        return False

    caption_ok = await enter_caption_lexical(page, caption)

    if not caption_ok:
        warn("Caption could not be entered — continuing anyway (post may have no caption)")
    await save_screenshot(page, "06_after_caption")
