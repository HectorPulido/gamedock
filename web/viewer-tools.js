/* Same-origin Xpra bridge. These counters observe real draw/decode work. */
window.GameDockViewer = (() => {
  function create(frame) {
    let client,
      originals,
      server,
      serverAt = 0,
      previous;
    let updates = 0,
      frames = 0,
      decoded = 0,
      decodedFrames = 0,
      bytes = 0;
    let decodeTotal = 0,
      decodeCount = 0,
      errors = 0;
    let codecs = new Map(),
      pending = new Map();
    function connect() {
      const next = frame.contentWindow?.client;
      if (!next?.connected || !next.packet_handlers?.draw) return false;
      if (next === client) return true;
      dispose();
      client = next;
      const draw = client.packet_handlers.draw;
      const ack = client.do_send_damage_sequence;
      const receive = function (packet) {
        const code = frame.contentWindow.Utilities.s(packet[6]);
        updates++;
        const complete = !packet[10]?.flush;
        if (complete) frames++;
        bytes += packet[7]?.byteLength ?? packet[7]?.length ?? 0;
        codecs.set(code, (codecs.get(code) || 0) + 1);
        pending.set(packet[8], { complete, started: performance.now() });
        if (pending.size > 4096) pending.delete(pending.keys().next().value);
        return draw.call(this, packet);
      };
      const acknowledge = function (
        sequence,
        wid,
        width,
        height,
        micros,
        error,
      ) {
        const item = pending.get(sequence);
        if (micros >= 0 && !error) {
          decoded++;
          if (item?.complete) decodedFrames++;
          decodeTotal += micros / 1000;
          decodeCount++;
        } else errors++;
        pending.delete(sequence);
        return ack.call(this, sequence, wid, width, height, micros, error);
      };
      client.packet_handlers.draw = receive;
      client.do_send_damage_sequence = acknowledge;
      const doc = frame.contentDocument;
      const info = (event) => {
        server = event.data;
        serverAt = performance.now();
      };
      doc.addEventListener("info-response", info);
      originals = { draw, ack, receive, acknowledge, doc, info };
      return true;
    }
    function dispose() {
      if (originals && client) {
        if (client.packet_handlers.draw === originals.receive)
          client.packet_handlers.draw = originals.draw;
        if (client.do_send_damage_sequence === originals.acknowledge)
          client.do_send_damage_sequence = originals.ack;
        originals.doc.removeEventListener("info-response", originals.info);
      }
      client = originals = server = previous = undefined;
      serverAt =
        updates =
        frames =
        decoded =
        decodedFrames =
        bytes =
        decodeTotal =
        decodeCount =
        errors =
          0;
      pending.clear();
      codecs.clear();
    }
    function focus() {
      const xpra = frame.contentWindow?.client;
      if (!xpra?.connected || frame.hidden) return;
      frame.contentWindow.focus();
      xpra.capture_keyboard = true;
      xpra.container.tabIndex = 0;
      xpra.container.focus({ preventScroll: true });
      const windows = Object.values(xpra.id_to_window || {}).filter(
        (win) => win && !win.tray && !win.override_redirect && !win.minimized,
      );
      const target = windows.reduce(
        (best, win) =>
          !best ||
          Number(win.stacking_layer || 0) >= Number(best.stacking_layer || 0)
            ? win
            : best,
        null,
      );
      if (target) {
        xpra.focused_wid = 0;
        xpra.set_focus(target);
      }
    }
    function filter(mode) {
      const doc = frame.contentDocument;
      if (!doc) return;
      let style = doc.querySelector("#gamedock-canvas-filter");
      if (!style) {
        style = doc.createElement("style");
        style.id = "gamedock-canvas-filter";
        doc.head.append(style);
      }
      const rendering = mode === "crisp" ? "pixelated" : "auto";
      frame.style.imageRendering = rendering;
      style.textContent = `canvas { image-rendering: ${rendering} !important; }`;
      for (const win of Object.values(
        frame.contentWindow?.client?.id_to_window || {},
      )) {
        for (const ctx of [win.canvas_ctx, win.offscreen_canvas_ctx])
          if (ctx) ctx.imageSmoothingEnabled = mode !== "crisp";
      }
    }
    function flatten(value, prefix = "", result = {}) {
      for (const [key, item] of Object.entries(value || {})) {
        const name = prefix ? prefix + "." + key : key;
        if (item && typeof item === "object" && !Array.isArray(item))
          flatten(item, name, result);
        else result[name] = item;
      }
      return result;
    }
    function sample() {
      if (!connect()) return { connected: false };
      const now = performance.now();
      const current = {
        at: now,
        updates,
        frames,
        decoded,
        decodedFrames,
        bytes,
        decodeTotal,
        decodeCount,
      };
      const dt = previous ? (now - previous.at) / 1000 : 0;
      const result = {
        connected: true,
        warming: !dt,
        codecs: [...codecs]
          .sort((a, b) => b[1] - a[1])
          .map(([code]) => code)
          .join(", "),
        decode_errors: errors,
        client_codecs: client.supported_encodings.join(", "),
        h264_status: codecs.has("h264")
          ? "Receiving H.264"
          : client.supported_encodings.includes("h264")
            ? "Supported; waiting for video frames"
            : !frame.contentWindow.isSecureContext
              ? "Unavailable: use HTTPS or localhost"
              : "Unavailable: browser decoder not supported",
      };
      if (dt > 0) {
        for (const [field, count] of Object.entries({
          delivered_fps: "frames",
          delivered_updates: "updates",
          decoded_fps: "decodedFrames",
          decoded_updates: "decoded",
        }))
          result[field] = Math.max(0, (current[count] - previous[count]) / dt);
        result.image_mbps = Math.max(
          0,
          ((bytes - previous.bytes) * 8) / dt / 1e6,
        );
        result.decode_ms =
          decodeCount > previous.decodeCount
            ? (decodeTotal - previous.decodeTotal) /
              (decodeCount - previous.decodeCount)
            : 0;
      }
      previous = current;
      const flat = flatten(server);
      result.server_age = serverAt ? (now - serverAt) / 1000 : null;
      for (const [key, value] of Object.entries(flat))
        if (key.startsWith("gamedock."))
          result[key.slice(9)] =
            typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value)
              ? Number(value)
              : value;
      for (const [key, pattern] of Object.entries({
        bandwidth_budget_mbps: /(?:^|\.)bandwidth\.actual$/,
        bandwidth_window_mbps: /(?:^|\.)window\.\d+\.bandwidth-limit$/,
      })) {
        const entry = Object.entries(flat).find(([name]) => pattern.test(name));
        result[key] = entry ? Number(entry[1]) / 1e6 : null;
      }
      const latency = Object.entries(flat).find(([key]) =>
        /(?:^|\.)damage\.client-latency$/.test(key),
      );
      if (latency) result.roundtrip_ms = latency[1];
      // Request through Xpra's existing connection, only while the caller samples.
      client.send_info_request();
      return result;
    }
    return { connect, focus, filter, sample, dispose };
  }
  return { create };
})();
