"""GPU profile form round-trips without requiring hardware on the QA machine."""

from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, PASSWORD, rendered, ARTIFACTS

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL)
    page.get_by_label("Username", exact=True).fill("admin")
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Administration", exact=True).click()
    page.locator("#admin-nav").get_by_role("link", name="Games", exact=True).click()
    profile_id = "qa-gpu-form"
    form = page.locator("#profile")
    sid = None
    try:
        page.locator("#add-game").click()
        import json

        form.get_by_label("JSON definition").fill(
            json.dumps(
                {
                    "id": profile_id,
                    "name": "GPU form test",
                    "image": "gamedock-runtime:local",
                    "command": ["xterm"],
                }
            )
        )
        expect(form.get_by_label("Graphics acceleration")).to_have_value("none")
        expect(form.get_by_label("GPU device", exact=True)).to_be_disabled()
        for vendor in ("nvidia", "amd", "intel"):
            form.get_by_label("Graphics acceleration").select_option(vendor)
            device = "GPU-test-123" if vendor == "nvidia" else "/dev/dri/renderD129"
            form.get_by_label("GPU device", exact=True).fill(device)
            form.get_by_label("GPU host group IDs").fill("109, 44")
            form.get_by_role("button", name="Save game", exact=True).click()
            expect(
                form.get_by_role("button", name="Save game", exact=True)
            ).to_be_enabled()
            expect(page.locator("#notice")).to_contain_text("Game saved.")
            profile = next(
                g
                for g in page.request.get(URL + "/api/catalog").json()["games"]
                if g["id"] == profile_id
            )
            assert profile["gpu"] == {
                "vendor": vendor,
                "device": device,
                "groups": [109, 44],
            }
            assert (
                json.loads(form.get_by_label("JSON definition").input_value())["gpu"]
                == profile["gpu"]
            )
        form.get_by_label("GPU host group IDs").fill("not-a-group")
        form.get_by_role("button", name="Save game", exact=True).click()
        expect(form.get_by_role("button", name="Save game", exact=True)).to_be_enabled()
        expect(page.locator("#notice")).to_contain_text("comma-separated numbers")
        form.get_by_label("Graphics acceleration").select_option("none")
        form.get_by_role("button", name="Save game", exact=True).click()
        expect(form.get_by_role("button", name="Save game", exact=True)).to_be_enabled()
        expect(form.get_by_label("GPU device", exact=True)).to_be_disabled()
        profile = next(
            g
            for g in page.request.get(URL + "/api/catalog").json()["games"]
            if g["id"] == profile_id
        )
        assert profile["gpu"] == {"vendor": "none", "software_threads": 0}
        form.get_by_label("CPU rendering threads", exact=True).fill("3")
        form.get_by_role("button", name="Save game", exact=True).click()
        expect(form.get_by_role("button", name="Save game", exact=True)).to_be_enabled()
        expect(page.locator("#notice")).to_contain_text("Game saved.")
        page.reload()
        card = page.locator("article").filter(
            has=page.get_by_role("heading", name="GPU form test", exact=True)
        )
        card.get_by_role("button", name="Edit", exact=True).click()
        expect(form.get_by_label("Graphics acceleration")).to_have_value("none")
        expect(form.get_by_label("CPU rendering threads", exact=True)).to_have_value(
            "3"
        )
        form.get_by_label(
            "CPU rendering threads", exact=True
        ).scroll_into_view_if_needed()
        page.screenshot(path=str(ARTIFACTS / "graphics-profile.png"))
        # A GPU image can still run a profile that explicitly disables GPU.
        profile.update(
            image="gamedock-runtime-gpu-nvidia:local",
            gpu={"vendor": "none", "software_threads": 3},
            command=["glxgears", "-geometry", "640x480+540+100"],
        )
        assert page.request.put(URL + "/api/admin/games", data=profile).ok
        launched = page.request.post(URL + "/api/instances", data={"game": profile_id})
        assert launched.status == 201, launched.text()
        sid = launched.json()["id"]
        page.goto(URL + "/play/" + sid)
        remote = rendered(page)
        remote.wait_for_function(
            """() => [...document.querySelectorAll('canvas')].some(c => {
            const ctx=c.getContext('2d'); if(!ctx) return false;
            const d=ctx.getImageData(600,200,500,350).data; const colors=[0,0,0];
            for(let i=0;i<d.length;i+=16) {
                if(d[i]>100 && d[i+1]<70 && d[i+2]<70) colors[0]++;
                if(d[i+1]>100 && d[i]<70 && d[i+2]<70) colors[1]++;
                if(d[i+2]>100 && d[i]<70 && d[i+1]<70) colors[2]++;
            }
            return colors.every(n=>n>200);
        })""",
            timeout=20000,
        )
        page.locator("#player-settings-toggle").click()
        page.locator("#diagnostics-toggle").click()
        page.wait_for_function(
            "document.querySelector('[data-metric=\"gpu_renderer\"]').textContent.includes('llvmpipe')",
            timeout=20000,
        )
        expect(page.locator('[data-metric="software_threads"]')).to_have_text("3.0")
        page.screenshot(path=str(ARTIFACTS / "software-opengl.png"))
        print(
            "PASS: NVIDIA/AMD/Intel selection, device and group validation, JSON synchronization, save/reload and rendered llvmpipe OpenGL with configurable workers"
        )
    finally:
        if sid:
            page.request.delete(URL + "/api/instances/" + sid, data={})
        page.request.delete(URL + "/api/admin/games/" + profile_id, data={})
        browser.close()
