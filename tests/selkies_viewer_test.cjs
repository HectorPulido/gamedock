// Run with: node tests/selkies_viewer_test.cjs
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const sent = [], styles = new Map();
let focused = 0, timer, dirty = 0;
const canvas = {tabIndex: -1, focus() {focused++;}};
const document = {hidden: false, querySelector() {return canvas;},
  getElementById(id) {return styles.get(id);}, createElement() {return {};},
  head: {append(style) {styles.set(style.id, style);}}};
const win = {postMessage(message, origin) {sent.push({message, origin});}, focus() {focused++;},
  stream_stats: {latest: {t: Date.now(), fps: 24, encoded_fps: 30, mbps: 4, cpu_percent: 80, mem_used: 9000}},
  stream_info: {encoder: 'VAAPI', hardware: true, zero_copy: true},
  stream_client: {codec: 'h264', decoder: 'hardware'}};
const frame = {contentWindow: win, contentDocument: document, hidden: false};
const sandbox = {window: {}, document, location: {origin: 'https://example.test'},
  Date, performance, setInterval(fn) {timer = fn; return 1;}, clearInterval() {},
  GameDockFSR: {create() {return {enable() {}, dirty() {dirty++;}, dispose() {}, sample() {return {mode: 'fsr'};}};}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../web/viewer-tools.js'), 'utf8'), sandbox);
const viewer = sandbox.window.GameDockViewer.create(frame);
viewer.filter('fsr'); timer();
assert.ok(dirty > 0);
assert.match(styles.get('gamedock-vendor-ui').textContent, /display:none!important/);
assert.equal(sent.find(x => x.message.type === 'setScaleLocally').message.value, true);
assert.equal(sent.find(x => x.message.type === 'statsOpen').message.open, false);
viewer.audio(.5, true);
assert.equal(sent.at(-2).message.value, .5);
assert.equal(sent.at(-1).message.value, true);
viewer.diagnostics(true);
assert.equal(sent.at(-1).message.open, true);
const sample = viewer.sample();
assert.equal(sample.decoded_fps, 24);
assert.equal(sample.delivered_fps, 30);
assert.equal(sample.encoder, 'VAAPI');
assert.equal(sample.cpu_percent, undefined, 'Host CPU must not masquerade as container CPU');
assert.equal(sample.container_memory_mb, undefined);
win.stream_stats.latest.t -= 10000;
assert.equal(viewer.sample().decoded_fps, undefined, 'Stale metrics must not appear live');
viewer.focus(); assert.equal(focused, 2);
viewer.dispose(); assert.equal(sent.at(-1).message.open, false);
const allowed = new Set(['setScaleLocally', 'setVolume', 'setMute', 'statsOpen']);
assert.ok(sent.every(x => allowed.has(x.message.type) && x.origin === sandbox.location.origin));
console.log('Selkies viewer contract passed');
