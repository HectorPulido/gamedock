"""Exercise real upstream FSR shaders in Chromium with post-decode canvas input."""
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        args=[
            "--no-sandbox",
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
        ]
    )
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    page.on("console", lambda msg: print(msg.text))
    page.set_content(
        '<style>#stage{position:relative;width:1280px;height:720px}iframe{width:640px;height:360px;transform:scale(2);transform-origin:top left;border:0}.fsr-overlay{position:absolute;pointer-events:none}</style><div id="stage"><iframe id="frame"></iframe></div>'
    )
    for name in ["fsr1-shaders.js", "fsr.js"]:
        page.add_script_tag(path="/app/web/" + name)
    page.evaluate(
        """() => {
      const frame=document.querySelector('iframe');const doc=frame.contentDocument;
      doc.body.style.margin='0'; const c=doc.createElement('canvas');c.width=640;c.height=360;doc.body.append(c);
      const ctx=c.getContext('2d');ctx.fillStyle='red';ctx.fillRect(0,0,640,180);ctx.fillStyle='blue';ctx.fillRect(0,180,640,180);
      ctx.fillStyle='white';ctx.font='18px sans-serif';ctx.fillText('FSR 1 / EASU + RCAS / small chat',40,50);
      window.fsr=GameDockFSR.create(frame);fsr.enable(true);
      window.pointer=null;c.addEventListener('pointerdown',e=>window.pointer=[e.offsetX,e.offsetY]);
    }"""
    )
    page.wait_for_function("fsr.sample().frames > 0 || fsr.sample().reason")
    result = page.evaluate("fsr.sample()")
    assert result["mode"] == "fsr", result
    assert result["source"] == "640×360", result
    page.mouse.click(400, 200)
    assert page.evaluate("pointer") == [196, 96], page.evaluate("pointer")
    page.screenshot(path="/artifacts/fsr-colors.png")
    page.evaluate("fsr.dispose();fsr.enable(true)")
    page.wait_for_function("fsr.sample().frames > 1 || fsr.sample().reason")
    assert page.evaluate("fsr.sample().mode") == "fsr", page.evaluate("fsr.sample()")
    timings = []
    for _ in range(12):
        before = page.evaluate("fsr.sample().frames")
        page.evaluate("fsr.dirty()")
        page.wait_for_function("n=>fsr.sample().frames>n", arg=before)
        timings.append(page.evaluate("fsr.sample().submit_ms"))
    print("Steady CPU submission ms:", json.dumps(timings), flush=True)
    page.evaluate("fsr.enable(false)")
    assert page.locator("iframe").content_frame.locator(".fsr-overlay").count() == 0
    page.evaluate("fsr.enable(true)")
    page.locator("iframe").content_frame.locator(".fsr-overlay").wait_for()
    page.evaluate(
        'document.querySelector("iframe").contentDocument.querySelector(".fsr-overlay").getContext("webgl2").getExtension("WEBGL_lose_context").loseContext()'
    )
    page.wait_for_function('fsr.sample().reason.includes("context lost")')
    assert page.evaluate("fsr.sample().mode") == "smooth"
    assert page.locator("iframe").content_frame.locator(".fsr-overlay").count() == 0
    page.evaluate(
        'fsr.dispose();const get=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){return type==="webgl2"?null:get.call(this,type,...args)};window.fallback=GameDockFSR.create(document.querySelector("iframe"));fallback.enable(true)'
    )
    page.wait_for_function("fallback.sample().reason")
    assert page.evaluate("fallback.sample().mode") == "smooth"
    assert page.locator("iframe").content_frame.locator(".fsr-overlay").count() == 0
    assert page.locator("iframe").element_handle().content_frame().locator(
        "canvas"
    ).evaluate("c=>[c.width,c.height]") == [640, 360]
    print(
        "PASS: shader render, source dimensions, pointer passthrough, dispose/recreate, toggles, unsupported fallback"
    )
    browser.close()
    print(json.dumps(result))
