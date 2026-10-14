/* Same-origin Selkies bridge. Player preferences never change server encoding. */
window.GameDockViewer = (() => {
  function create(frame) {
    const fsr = GameDockFSR.create(frame);
    let filterMode = 'smooth', connectedWindow, renderTimer, diagnosticsOpen = false;
    let nativePanelAllowed = false, nativePanelOpen = false, nativePanelPending = false;
    let volume = 1, muted = false, resourceMetrics, resourceAt = 0, resourcePending = false;
    function post(type, options = {}) {
      frame.contentWindow?.postMessage({type, ...options}, location.origin);
    }
    function stylesheet(id, text) {
      const doc = frame.contentDocument;
      if (!doc?.head) return;
      let style = doc.getElementById(id);
      if (!style) { style = doc.createElement('style'); style.id = id; doc.head.append(style); }
      style.textContent = text;
    }
    function connect() {
      const win = frame.contentWindow;
      if (!win || !frame.contentDocument?.querySelector('canvas,video')) return false;
      if (win !== connectedWindow) {
        connectedWindow = win;
        // Keep input coordinates at the fixed source resolution. The outer
        // GameDock iframe handles fit/original/integer scaling locally.
        post('setScaleLocally', {value: true});
        post('setVolume', {value: volume});
        post('setMute', {value: muted});
        post('statsOpen', {open: diagnosticsOpen});
        applyNativePanel();

      }
      if (nativePanelPending) applyNativePanel();
      return true;
    }
    function applyNativePanel() {
      const show = nativePanelAllowed && nativePanelOpen;
      stylesheet('gamedock-vendor-ui', show ? '' : '.sidebar,.toggle-handle{display:none!important;pointer-events:none!important}');
      const sidebar = frame.contentDocument?.querySelector('.sidebar');
      if (sidebar && show !== sidebar.classList.contains('is-open'))
        post('toggleDashboard');
    }
    function allowNativePanel(allowed) {
      nativePanelAllowed = allowed === true;
      if (!nativePanelAllowed) nativePanelOpen = false;
      applyNativePanel();
    }
    function showNativePanel(open) {
      nativePanelOpen = nativePanelAllowed && open === true;
      nativePanelPending = nativePanelOpen;
      applyNativePanel();
    }
    function dispose() {
      clearInterval(renderTimer); renderTimer = undefined;
      if (connectedWindow) post('statsOpen', {open: false});
      connectedWindow = undefined; resourceMetrics = undefined; resourceAt = 0; fsr.dispose();
    }
    function focus() {
      if (frame.hidden) return;
      frame.contentWindow?.focus();
      const target = frame.contentDocument?.querySelector('canvas,video');
      if (target) { target.tabIndex = 0; target.focus({preventScroll: true}); }
    }
    function filter(mode) {
      filterMode = mode;
      fsr.enable(mode === 'fsr');
      stylesheet('gamedock-canvas-filter', `canvas,video{image-rendering:${mode === 'crisp' ? 'pixelated' : 'auto'}!important}`);
      connect();
      if (!renderTimer) {
        let lastConnect = 0;
        renderTimer = setInterval(() => {
          if (performance.now() - lastConnect > 500) { connect(); lastConnect = performance.now(); }
          if (filterMode === 'fsr' && !document.hidden && !frame.hidden) fsr.dirty();
        }, 1000 / 30);
      }
    }
    // Selkies supplies a single live cursor; never hide its native input cursor.
    function remotePointer() {}
    function audio(value, mute) {
      volume = Math.min(1, Math.max(0, Number(value)));
      muted = !!mute;
      post('setVolume', {value: volume}); post('setMute', {value: muted});
    }
    function diagnostics(open) {
      diagnosticsOpen = !!open;
      post('statsOpen', {open: diagnosticsOpen});
    }
    function sample() {
      const connected = connect(), win = frame.contentWindow;
      if (diagnosticsOpen && !resourcePending && typeof fetch === 'function') {
        resourcePending = true;
        fetch(new URL('api/gamedock/metrics', frame.src), {credentials: 'same-origin'})
          .then(response => response.ok ? response.json() : null)
          .then(data => { if (data?.backend === 'selkies') { resourceMetrics = data; resourceAt = Date.now(); } })
          .catch(() => {})
          .finally(() => {resourcePending = false;});
      }
      const latest = win?.stream_stats?.latest || {};
      const info = win?.stream_info || {}, client = win?.stream_client || {};
      const age = latest.t ? Math.max(0, (Date.now() - latest.t) / 1000) : null;
      const fresh = age != null && age < 5;
      const result = {
        connected, server_age: age,
        scaler: filterMode === 'fsr' ? fsr.sample() : {mode: filterMode},
        codecs: client.codec || info.codec || '—',
        encoder: info.encoder, capture_path: info.capture_path,
        decoder: client.decoder, decoder_evidence: client.decoder_evidence,
        hardware_encoder: info.hardware == null ? undefined : (info.hardware ? 'Yes' : 'No'),
        zero_copy: info.zero_copy == null ? undefined : (info.zero_copy ? 'Yes' : 'No'),
        transport: client.transport || 'WebSocket',
      };
      // No host CPU/RAM figures: Selkies reports host-wide values, not this container.
      if (fresh) Object.assign(result, {
        delivered_fps: latest.encoded_fps, decoded_fps: latest.fps,
        encode_ms: latest.encode_ms, pipeline_ms: latest.pipeline_ms,
        roundtrip_ms: latest.rtt_ms, image_mbps: latest.mbps,
        present_ms: latest.present_ms, frames_not_shown: latest.frames_not_shown,
      });
      if (resourceMetrics && Date.now() - resourceAt < 5000) {
        for (const key of ['game_cpu_percent','stream_cpu_percent','game_rss_mb','game_pss_mb',
          'stream_rss_mb','stream_pss_mb','container_memory_mb','container_cpu_percent',
          'gpu_vendor','gpu_renderer','target_hz']) result[key] = resourceMetrics[key];
      }
      return result;
    }
    return {connect, focus, filter, remotePointer, audio, diagnostics, sample, dispose, allowNativePanel, showNativePanel};
  }
  return {create};
})();
