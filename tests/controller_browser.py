"""Deterministic browser tests without requiring physical controller hardware."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 844, "height": 390}, is_mobile=True, has_touch=True
        )
        page = await context.new_page()
        html = Path("/repo/web/player.html").read_text()
        import re

        html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
        await page.route(
            "https://gamedock.test/",
            lambda route: route.fulfill(body=html, content_type="text/html"),
        )
        await page.goto("https://gamedock.test/")
        await page.add_style_tag(content=Path("/repo/web/style.css").read_text())
        await page.add_style_tag(content=Path("/repo/web/player.css").read_text())
        await page.evaluate("""() => {
          HTMLElement.prototype.setPointerCapture = () => {};
          window.states = []; window.mockPad = null;
          window.fetch = async (url, options) => { states.push(JSON.parse(options.body)); return {ok:true,json:async()=>({mode:'keyboard'})}; };
          navigator.getGamepads = () => [window.mockPad];
          const frame = document.querySelector('#desktop-frame');
          frame.contentWindow.client = {connected:true};
          document.querySelector('#desktop-stage').style.height = '300px';
        }""")
        await page.add_script_tag(content=Path("/repo/web/nipplejs.js").read_text())
        await page.add_script_tag(content=Path("/repo/web/gamepad.js").read_text())
        await page.evaluate(
            "window.controller = GameDockController.create(document.querySelector('#desktop-frame'), 'test')"
        )
        await page.wait_for_timeout(100)
        assert await page.locator("#touch-controller").is_visible()
        # Independent pointer captures allow stick + multiple buttons together.
        # Feed pointer events through the real NippleJS handlers.
        rect = await page.locator(".touch-stick").bounding_box()
        x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
        await page.locator(".touch-stick").dispatch_event(
            "pointerdown",
            {
                "pointerId": 1,
                "clientX": x,
                "clientY": y,
                "pageX": x,
                "pageY": y,
                "buttons": 1,
            },
        )
        await page.locator("body").dispatch_event(
            "pointermove",
            {
                "pointerId": 1,
                "clientX": x + 35,
                "clientY": y,
                "pageX": x + 35,
                "pageY": y,
                "buttons": 1,
            },
        )
        await page.locator('[data-button="0"]').dispatch_event(
            "pointerdown", {"pointerId": 2}
        )
        await page.locator('[data-button="2"]').dispatch_event(
            "pointerdown", {"pointerId": 3}
        )
        await page.wait_for_timeout(120)
        assert await page.evaluate(
            "states.some(s => s.buttons[0] && s.buttons[2] && s.axes.some(v=>v!==0))"
        )
        await page.locator('[data-button="0"]').dispatch_event(
            "pointercancel", {"pointerId": 2}
        )
        await page.locator('[data-button="2"]').dispatch_event(
            "pointerup", {"pointerId": 3}
        )
        await page.locator("body").dispatch_event(
            "pointerup", {"pointerId": 1, "clientX": x + 35, "clientY": y, "buttons": 0}
        )
        await page.wait_for_timeout(120)
        assert await page.evaluate(
            "states.at(-1).buttons.every(v=>!v) && states.at(-1).axes.every(v=>v===0)"
        )
        await page.evaluate(
            "mockPad = {index:0,id:'Test USB/Bluetooth',mapping:'standard',connected:true,axes:[.7,0,0,0],buttons:Array.from({length:17},(_,i)=>({pressed:i===0}))}"
        )
        await page.wait_for_timeout(120)
        assert await page.evaluate(
            "states.at(-1).axes[0]===.7 && states.at(-1).buttons[0]"
        )
        await page.evaluate("mockPad = null")
        await page.wait_for_timeout(120)
        assert await page.evaluate(
            "states.at(-1).buttons.every(v=>!v) && states.at(-1).axes.every(v=>v===0)"
        )
        await page.evaluate("document.querySelector('#physical-controller').click()")
        await page.evaluate(
            "mockPad = {index:0,id:'Test USB/Bluetooth',mapping:'standard',connected:true,axes:[.7,0,0,0],buttons:Array.from({length:17},(_,i)=>({pressed:i===0}))}"
        )
        await page.wait_for_timeout(120)
        assert await page.evaluate(
            "states.at(-1).buttons.every(v=>!v) && states.at(-1).axes.every(v=>v===0)"
        )
        assert await page.evaluate(
            "localStorage.getItem('gamedock-physical-controller') === 'off'"
        )
        await page.select_option("#controller-mode", "off", force=True)
        assert not await page.locator("#touch-controller").is_visible()
        assert await page.evaluate(
            "localStorage.getItem('gamedock-controller-mode') === 'off'"
        )
        await page.select_option("#controller-mode", "touch", force=True)
        await page.screenshot(path="/tmp/artifacts/controller-mobile.png")
        await page.evaluate("controller.dispose()")
        await browser.close()
        print(
            "PASS: mobile detection, simultaneous touch, cancellation, standard physical gamepad polling, disconnect and disable"
        )


asyncio.run(main())
