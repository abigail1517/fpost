# ── Step 6: Enter caption ─────────────────────────────────────────────
    step("Entering caption text")
    info(f"Caption to type ({len(caption)} chars): {caption[:80]}")

    async def enter_caption_lexical(page, caption: str) -> bool:
        """
        Robust caption entry for Facebook's Lexical editor.
        Tries 4 strategies in order, returns True on first success.
        """

        LEXICAL_SELECTORS = [
            'div[data-lexical-editor="true"][contenteditable="true"]',
            'div[contenteditable="true"][aria-placeholder="Describe your reel..."]',
            'div[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"]',
        ]

        # ── Strategy 1: clipboard paste (most reliable for Lexical) ──────
        async def strategy_clipboard(field):
            info("Strategy 1: clipboard paste via execCommand")
            await field.click(timeout=5_000)
            await asyncio.sleep(0.4)
            # Select all & delete any existing content
            await page.keyboard.press("Control+a")
            await asyncio.sleep(0.2)
            await page.keyboard.press("Backspace")
            await asyncio.sleep(0.2)
            # Write to clipboard then paste
            await page.evaluate(
                "(text) => navigator.clipboard.writeText(text).catch(() => {})",
                caption,
            )
            await asyncio.sleep(0.3)
            await page.keyboard.press("Control+v")
            await asyncio.sleep(0.8)

        # ── Strategy 2: execCommand insertText ───────────────────────────
        async def strategy_exec_command(field):
            info("Strategy 2: document.execCommand('insertText')")
            await field.click(timeout=5_000)
            await asyncio.sleep(0.3)
            await page.evaluate(
                """(el, text) => {
                    el.focus();
                    // Clear
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                    // Insert
                    document.execCommand('insertText', false, text);
                }""",
                [field, caption],
            )
            await asyncio.sleep(0.5)

        # ── Strategy 3: Lexical dispatchEvent with InputEvent ────────────
        async def strategy_input_event(field):
            info("Strategy 3: InputEvent dispatch on Lexical editor")
            await field.click(timeout=5_000)
            await asyncio.sleep(0.3)
            await page.evaluate(
                """(el, text) => {
                    el.focus();
                    // Select all existing text
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    sel.removeAllRanges();
                    sel.addRange(range);
                    // Fire an insertText InputEvent — Lexical listens for this
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

        # ── Strategy 4: slow keyboard.type fallback ───────────────────────
        async def strategy_keyboard_type(field):
            info("Strategy 4: page.keyboard.type (slow fallback)")
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

                    # Verify text landed
                    txt = await field.evaluate(
                        "el => (el.innerText || el.textContent || '').trim()"
                    )
                    if txt and len(txt) > 2:
                        ok(f"Caption entered via strategy {i} / selector '{sel}' ({len(txt)} chars)")
                        return True
                    else:
                        warn(f"Strategy {i} / '{sel}': field still empty after attempt")
                except Exception as e:
                    warn(f"Strategy {i} / '{sel}' raised: {e}")

        return False

    caption_ok = await enter_caption_lexical(page, caption)

    if not caption_ok:
        warn("Caption could not be entered — continuing anyway (post may have no caption)")
    await save_screenshot(page, "06_after_caption")
