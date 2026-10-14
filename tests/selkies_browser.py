"""Real Selkies acceptance against an isolated GameDock QA deployment.

QA_URL, QA_ENV_FILE, QA_ARTIFACTS and QA_GAME_ID select the disposable deployment.
Requires an enabled OpenTTD profile. Never targets production by default.
"""
import json
import os
import time
from playwright.sync_api import sync_playwright, expect
from browser_helpers import URL, ARTIFACTS, PASSWORD, rendered, centered

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=os.getenv('QA_BROWSER_EXECUTABLE') or None,
        args=['--autoplay-policy=no-user-gesture-required'])
    context = browser.new_context(ignore_https_errors=True, viewport={'width':1600,'height':1000})
    context.add_init_script("""(() => {
      window.__qaAudioGains=[];window.__qaAudioContexts=[];window.__qaAudioAnalysers=[];
      const A=window.AudioContext || window.webkitAudioContext;
      if(!A)return;
      const original=A.prototype.createGain;
      A.prototype.createGain=function(...args){
        const node=original.apply(this,args);window.__qaAudioGains.push(node);
        const analyser=this.createAnalyser();analyser.fftSize=2048;node.connect(analyser);window.__qaAudioAnalysers.push(analyser);
        if(!window.__qaAudioContexts.includes(this))window.__qaAudioContexts.push(this);
        return node;
      };
    })();""")
    login = context.request.post(URL+'/api/auth/login',data={'username':'admin','password':PASSWORD})
    assert login.ok, login.text()
    catalog = context.request.get(URL+'/api/catalog').json()
    game_id = os.getenv('QA_GAME_ID','openttd')
    profile = next(g for g in catalog['games'] if g['id']==game_id)
    launch = context.request.post(URL+'/api/instances',data={'game':game_id})
    assert launch.status==201, launch.text()
    sid = launch.json()['id']
    page = context.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    summary={'sid':sid,'profile':game_id,'checks':[]}
    try:
        page.goto(URL+'/play/'+sid)
        remote=rendered(page)
        centered(page)
        assert remote.locator('.sidebar:visible,.toggle-handle:visible').count()==0
        summary['checks'].append('native sidebar absent')
        expect(page.locator('.player-header')).to_be_visible()
        expect(page.locator('#session-tabs')).to_contain_text(profile['name'])
        for scale in ['fit','original','integer']:
            page.locator('#player-settings-toggle').click()
            page.locator('#viewer-scale').select_option(scale)
            page.locator('#player-settings-close').click()
            centered(page)
        summary['checks'].append('fit/original/integer keep centered source geometry')
        page.locator('#player-settings-toggle').click()
        page.locator('#viewer-scale').select_option('fit')
        for mode in ['smooth','crisp','fsr']:
            page.locator('#canvas-filter').select_option(mode)
            page.wait_for_timeout(1500)
            assert remote.locator('#gamedock-canvas-filter').count()==1
        page.locator('#audio-volume').evaluate("el => {el.value='0.4';el.dispatchEvent(new Event('input',{bubbles:true}));}")
        page.locator('#audio-muted').check()
        remote.wait_for_function('window.__qaAudioGains?.some(n=>n.gain.value===0)',timeout=15000)
        page.locator('#audio-muted').uncheck()
        remote.wait_for_function('window.__qaAudioGains?.some(n=>Math.abs(n.gain.value-.4)<.01)',timeout=15000)
        summary['audio']=remote.evaluate('({gains:window.__qaAudioGains.map(n=>n.gain.value),contexts:window.__qaAudioContexts.map(c=>c.state)})')
        summary['checks'].append('real browser WebAudio gain/mute applied')
        if os.getenv('QA_AUDIO_TEST') == '1':
            # Host harness injects a known tone through this disposable game's
            # PulseAudio sink after seeing the marker, never through the browser.
            (ARTIFACTS/'audio-ready.json').write_text(json.dumps({'sid':sid}))
            remote.wait_for_function("""() => window.__qaAudioAnalysers.some(a=>{
                const samples=new Float32Array(a.fftSize);a.getFloatTimeDomainData(samples);
                const rms=Math.sqrt(samples.reduce((n,v)=>n+v*v,0)/samples.length);
                window.__qaAudioRms=Math.max(window.__qaAudioRms||0,rms);
                return rms>.005;
            })""",timeout=30000)
            summary['audio']['decoded_rms_peak']=remote.evaluate('window.__qaAudioRms')
            summary['checks'].append('PulseAudio tone decoded to nonzero browser PCM')
            (ARTIFACTS/'selkies-audio-proof.json').write_text(json.dumps(summary['audio'],indent=2))

        # Reject exposing server encoder knobs in the custom settings dialog.
        assert page.locator('#player-settings input[type=number]').count()==0
        assert page.locator('#player-settings').get_by_text('bitrate',exact=False).count()==0
        page.locator('#diagnostics-toggle').click()
        page.wait_for_timeout(4000)
        expect(page.locator('#streaming-diagnostics')).to_be_visible()
        stats=remote.evaluate('({fps:window.fps,stats:window.stream_stats,info:window.stream_info,client:window.stream_client})')
        summary['stream']=stats
        summary['scaler']=page.evaluate('viewer.sample().scaler')
        assert (stats.get('stats') or {}).get('latest'), 'On-demand streaming metrics unavailable'
        assert (stats['stats']['latest'].get('fps') or 0) >= 10, 'Stream below acceptance floor'
        summary['checks'].append('browser filters/audio controls and on-demand diagnostics')
        page.locator('#diagnostics-close').click()
        page.locator('#fullscreen').click()
        page.wait_for_function('!!document.fullscreenElement')
        page.locator('#fullscreen').click()
        page.wait_for_function('!document.fullscreenElement')
        summary['checks'].append('fullscreen enter/exit')
        page.screenshot(path=str(ARTIFACTS/'selkies-player.png'),full_page=True)
        # A second tab must join without evicting the first tab or opening another game.
        second=context.new_page(); second.goto(URL+'/play/'+sid)
        second_remote=rendered(second)
        second_remote.wait_for_function('Number(window.fps)>0',timeout=15000)
        assert context.request.get(URL+'/api/instances/'+sid).json()['status']=='running'
        second.close(); page.bring_to_front(); rendered(page)
        remote.wait_for_function('Number(window.fps)>0',timeout=15000)
        summary['checks'].append('two tabs and owner handover keep game alive')
        assert not errors, errors
        summary['page_errors']=errors
        (ARTIFACTS/'selkies-browser.json').write_text(json.dumps(summary,indent=2))
        print(json.dumps({'checks':summary['checks'],'artifacts':str(ARTIFACTS)}))
    finally:
        context.request.delete(URL+'/api/instances/'+sid)
        browser.close()
