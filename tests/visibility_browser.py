"""Real tab switching and streaming samples against a disposable HTTPS Xpra URL.

Requires headed Chromium with Playwright focus emulation disabled (see
Dockerfile.visibility-browser); otherwise every tab reports document.hidden=False.
QA_XPRA_URL must target a disposable runtime, never a user's desktop.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

url = os.environ['QA_XPRA_URL']
artifacts = Path(os.getenv('QA_ARTIFACTS', '/artifacts'))
artifacts.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, executable_path=os.getenv('QA_BROWSER_EXECUTABLE', '/usr/bin/chromium'))
    context = browser.new_context(ignore_https_errors=True, bypass_csp=True, viewport={'width': 1360, 'height': 850})
    page = context.new_page()
    page.goto(url)
    page.bring_to_front()
    page.wait_for_function('() => window.client?.connected', polling=100, timeout=60000)
    page.evaluate('''() => {
      window.qaCounters = {frames:0, decoded:0, errors:0, bytes:0, codecs:{}};
      const draw=client.packet_handlers.draw, ack=client.do_send_damage_sequence;
      const pending=new Map();
      client.packet_handlers.draw=function(packet) {
        const code=Utilities.s(packet[6]), complete=!packet[10]?.flush;
        qaCounters.bytes+=packet[7]?.byteLength ?? packet[7]?.length ?? 0;
        qaCounters.codecs[code]=(qaCounters.codecs[code]||0)+1;
        if(complete) qaCounters.frames++;
        pending.set(packet[8],complete);
        return draw.call(this,packet);
      };
      client.do_send_damage_sequence=function(sequence,wid,width,height,micros,error) {
        if(micros>=0&&!error) { if(pending.get(sequence)) qaCounters.decoded++; }
        else qaCounters.errors++;
        pending.delete(sequence);
        return ack.call(this,sequence,wid,width,height,micros,error);
      };
    }''')

    def info():
        page.evaluate('client.send_info_request()')
        page.wait_for_timeout(350)
        return page.evaluate('client.server_last_info')

    def source(data):
        return next(iter(data['client'].values()))

    page.wait_for_timeout(8000)
    cdp = context.new_cdp_session(page)
    ctxid = cdp.send('Target.getTargetInfo')['targetInfo']['browserContextId']
    with context.expect_page() as new_page:
        cdp.send('Target.createTarget', {'url':'about:blank', 'browserContextId':ctxid, 'newWindow':False})
    other = new_page.value
    recoveries=[]
    for cycle in range(4):
        other.bring_to_front()
        page.wait_for_function('() => document.hidden', polling=100)
        page.wait_for_timeout(1200)
        hidden = info()
        hidden_batch = source(hidden)['window']['1']['batch']
        assert hidden_batch['locked'], hidden_batch
        page.bring_to_front()
        page.wait_for_function('() => !document.hidden', polling=100)
        page.locator('canvas').first.click(position={'x':350,'y':300})
        page.keyboard.press('ArrowRight')
        page.mouse.move(450+cycle*10,350)
        page.wait_for_timeout(700)
        recovered=info()
        batch=source(recovered)['window']['1']['batch']
        assert batch['locked'] is False, batch
        delay=batch.get('delay',0)
        current=delay.get('last',delay.get('cur',0)) if isinstance(delay,dict) else delay
        assert current<=batch['max-delay'], batch
        recoveries.append({'cycle':cycle+1,'hidden_locked':True,'locked':False,'delay_ms':current,'maximum_ms':batch['max-delay']})
    other.close()
    page.wait_for_timeout(4000)
    before=page.evaluate('({...qaCounters,at:performance.now()})')
    samples=[]
    for _ in range(12):
        page.wait_for_timeout(1000)
        data=info()
        samples.append(float(data['gamedock']['capture_fps']))
    after=page.evaluate('({...qaCounters,at:performance.now()})')
    seconds=(after['at']-before['at'])/1000
    last=info()
    src=source(last)
    window=src['window']['1']
    result={
      'recoveries':recoveries,'target_hz':last['gamedock']['target_hz'],
      'capture_fps':round(sum(samples)/len(samples),2),
      'delivered_fps':round((after['frames']-before['frames'])/seconds,2),
      'decoded_fps':round((after['decoded']-before['decoded'])/seconds,2),
      'image_mbps':round(8*(after['bytes']-before['bytes'])/seconds/1e6,3),
      'decode_errors':after['errors'],'codecs':after['codecs'],
      'window_bandwidth_limit':window['bandwidth-limit'],
      'settings':last['gamedock']['settings'],
    }
    assert after['errors']==0,result
    assert after['codecs'].get('h264',0)>0,result
    assert window['bandwidth-limit']==int(float(os.getenv('QA_BANDWIDTH_MBPS','6'))*1e6),result
    (artifacts/f"visibility-{os.getenv('QA_BANDWIDTH_MBPS','6')}mbps.json").write_text(json.dumps(result,indent=2)+'\n')
    page.screenshot(path=str(artifacts/'visibility-recovered.png'))
    print(json.dumps(result),flush=True)
    browser.close()
