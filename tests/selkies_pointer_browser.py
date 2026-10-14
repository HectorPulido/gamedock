"""Actual OpenTTD native button hits through every GameDock scale mode."""
import json, os
from playwright.sync_api import sync_playwright
from browser_helpers import URL, ARTIFACTS, PASSWORD, rendered

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=os.getenv('QA_BROWSER_EXECUTABLE') or None)
    ctx=browser.new_context(ignore_https_errors=True,viewport={'width':1600,'height':1000})
    login=ctx.request.post(URL+'/api/auth/login',data={'username':'admin','password':PASSWORD});assert login.ok
    launch=ctx.request.post(URL+'/api/instances',data={'game':os.getenv('QA_GAME_ID','openttd')});assert launch.status==201,launch.text()
    sid=launch.json()['id'];page=ctx.new_page();result={'sid':sid,'scales':[]}
    try:
        page.goto(URL+'/play/'+sid);remote=rendered(page)
        def click_source(x,y):
            rect=page.locator('#desktop-frame').bounding_box()
            page.mouse.click(rect['x']+x/960*rect['width'],rect['y']+y/540*rect['height'])
            page.wait_for_timeout(600)
        # First-run survey can obscure the native New Game button. No is a local
        # OpenTTD preference and sends no external request.
        click_source(410,306)
        for scale in ['fit','original','integer']:
            page.locator('#player-settings-toggle').click()
            page.locator('#canvas-filter').select_option('smooth')
            page.locator('#viewer-scale').select_option(scale)
            page.locator('#player-settings-close').click();page.wait_for_timeout(300)
            click_source(400,185)
            page.screenshot(path=str(ARTIFACTS/f'selkies-pointer-{scale}.png'))
            result['scales'].append({'mode':scale,'source_button':[400,185],'frame':page.locator('#desktop-frame').bounding_box()})
            # OpenTTD Escape does not close this native generation window.
            # Hit its small native X so the next scale really reopens New Game.
            click_source(255,136)
        (ARTIFACTS/'selkies-pointer.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
    finally:
        ctx.request.delete(URL+'/api/instances/'+sid);browser.close()
