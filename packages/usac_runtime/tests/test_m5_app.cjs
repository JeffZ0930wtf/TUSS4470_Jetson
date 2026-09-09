"use strict";

// Execute the repository's actual controller functions with a deliberately
// small DOM/HTTP stub. This verifies task ownership without launching a server.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const sourcePath = path.join(__dirname, "..", "src", "usac_runtime", "web", "m5-app.js");
const source = fs.readFileSync(sourcePath, "utf8")
  .replace(/init\(\)\.catch\(\(error\) => toast\(error\.message\)\);\s*$/, "");

function makeHarness() {
  const nodes = new Map();
  const counters = Array.from({ length: 4 }, () => ({ textContent: "" }));
  const requests = [];
  const timers = [];
  const responses = [];

  function node(selector) {
    if (!nodes.has(selector)) {
      nodes.set(selector, {
        value: "",
        disabled: false,
        hidden: false,
        textContent: "",
        className: "",
        dataset: {},
        listeners: {},
        addEventListener(event, handler) { this.listeners[event] = handler; },
        querySelectorAll() { return selector === "#capture-counters" ? counters : []; },
        replaceChildren() {},
        getContext() {
          return {
            clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
            strokeStyle: "", lineWidth: 0,
          };
        },
      });
    }
    return nodes.get(selector);
  }

  const sandbox = {
    console,
    document: { querySelector: node, querySelectorAll: () => [] },
    localStorage: { getItem: () => null, setItem() {} },
    window: { setTimeout(handler, delay) { timers.push({ handler, delay }); return timers.length; } },
    URLSearchParams,
    Uint8Array,
    Uint16Array,
    fetch: async (requestPath, options = {}) => {
      requests.push({ path: requestPath, ...options });
      assert.ok(responses.length, `unexpected request: ${requestPath}`);
      const response = await responses.shift();
      return {
        ok: response.ok !== false,
        json: async () => response.payload ?? {},
        arrayBuffer: async () => Uint8Array.from(response.bytes ?? [1, 0, 2, 0]).buffer,
      };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return {
    node, requests, responses, timers,
    run: (code) => vm.runInContext(code, sandbox),
  };
}

async function main() {
  const pendingStart = makeHarness();
  Object.entries({
    "#capture-mode": "PERIODIC", "#save-policy": "SAVE_ALL",
    "#period-us": "1000000", "#periodic-count": "2", "#lease-timeout": "3000",
  }).forEach(([selector, value]) => { pendingStart.node(selector).value = value; });
  pendingStart.run('state.connected = true; state.config = {state: "APPLIED", actual: {profile_sha256: "abc", device_config_crc32: 123}}; pollSession = async () => {};');
  let finishStart;
  pendingStart.responses.push(
    new Promise((resolve) => { finishStart = resolve; }),
    { payload: { session_id: "duplicate", schedule_id: "duplicate", acquired_count: 0 } },
  );

  const firstStart = pendingStart.run("startCapture()");
  await Promise.resolve();
  const secondStart = pendingStart.run("startCapture()");
  assert.equal(pendingStart.run("Boolean(state.active && state.active.pending)"), true);
  assert.equal(pendingStart.node("#capture-start").disabled, true);
  assert.equal(pendingStart.node("#capture-stop").disabled, true);
  assert.equal(
    pendingStart.requests.filter((request) => request.path === "/api/v1/periodic/start").length,
    1,
  );
  finishStart({ payload: { session_id: "session-pending", schedule_id: "schedule-pending", acquired_count: 0 } });
  await Promise.all([firstStart, secondStart]);

  const deviceRetry = makeHarness();
  deviceRetry.responses.push({ ok: false, payload: { detail: "initial query failed" } });
  await deviceRetry.run("refreshDevice()").catch(() => {});
  let refreshTimers = deviceRetry.timers.filter((timer) => timer.delay === 1000);
  assert.equal(refreshTimers.length, 1);
  deviceRetry.responses.push({
    payload: {
      connected: true, health: "NORMAL", activity: "IDLE", backend: "SIMULATOR",
      device_id: "11".repeat(16), firmware: { major: 0, minor: 1, patch: 0, build: 1 },
    },
  });
  await refreshTimers[0].handler();
  refreshTimers = deviceRetry.timers.filter((timer) => timer.delay === 1000);
  assert.equal(refreshTimers.length, 2);
  assert.equal(deviceRetry.run("state.connected"), true);

  const ui = makeHarness();
  ui.run("bindActions(); state.connected = true;");

  ui.run('state.active = {mode: "PERIODIC", session_id: "session-1", schedule_id: "schedule-1"}; setHardwareActions();');
  ui.responses.push({ ok: false, payload: { detail: "draft rejected while capture is active" } });
  await ui.node("#save-draft-button").listeners.click();
  assert.equal(ui.run("state.active.mode"), "PERIODIC");
  assert.equal(ui.node("#capture-stop").disabled, false);

  Object.entries({
    "#capture-mode": "PERIODIC", "#save-policy": "SAVE_ALL",
    "#trigger-source": "EXTERNAL_SYNC_SLAVE", "#sync-timeout": "5000",
    "#period-us": "1000000", "#periodic-count": "2", "#lease-timeout": "3000",
  }).forEach(([selector, value]) => { ui.node(selector).value = value; });
  ui.run("updateMode()");
  assert.equal(ui.node("#trigger-fields").hidden, true);
  assert.equal(ui.node("#trigger-source").disabled, true);
  assert.equal(ui.node("#periodic-trigger-hint").hidden, false);
  ui.run('state.active = null; state.config = {state: "APPLIED", actual: {profile_sha256: "abc", device_config_crc32: 123}}; pollSession = async () => {};');
  ui.responses.push({ payload: { session_id: "session-1", schedule_id: "schedule-1", acquired_count: 0 } });
  await ui.run("startCapture()");
  const periodicRequest = JSON.parse(ui.requests.at(-1).body);
  assert.equal(Object.hasOwn(periodicRequest, "trigger_source"), false);
  assert.equal(Object.hasOwn(periodicRequest, "sync_timeout_ms"), false);

  const live = makeHarness();
  live.run('state.active = {mode: "PERIODIC", session_id: "session-2", schedule_id: "schedule-2"};');
  live.responses.push(
    { payload: { state: "RUNNING", acquired_count: 1, last_capture_id: "capture-1" } },
    { bytes: [1, 0, 2, 0] },
  );
  await live.run("pollSession()");
  live.responses.push(
    { payload: { state: "RUNNING", acquired_count: 2, last_capture_id: "capture-2" } },
    { bytes: [3, 0, 4, 0] },
  );
  await live.run("pollSession()");
  assert.deepEqual(
    live.requests.filter((request) => request.path.endsWith("/samples")).map((request) => request.path),
    ["/api/v1/captures/capture-1/samples", "/api/v1/captures/capture-2/samples"],
  );
  assert.equal(live.run('Object.hasOwn(state, "waveformSamples")'), false);

  const retry = makeHarness();
  retry.run('state.active = {mode: "PERIODIC", session_id: "session-3", schedule_id: "schedule-3"};');
  retry.responses.push(
    { payload: { state: "RUNNING", acquired_count: 1, last_capture_id: "capture-3" } },
    { ok: false },
  );
  const timersBeforeFailure = retry.timers.length;
  await retry.run("pollSession()");
  assert.ok(retry.timers.length > timersBeforeFailure);
  assert.equal(retry.run("state.active.session_id"), "session-3");

  const terminal = makeHarness();
  terminal.run('state.active = {mode: "SWEEP", session_id: "session-4"};');
  terminal.responses.push(
    { payload: { state: "COMPLETED", acquired_count: 1, last_capture_id: "capture-4" } },
    { ok: false },
    { payload: { items: [], next_cursor: null } },
  );
  await terminal.run("pollSession()");
  assert.equal(terminal.run("state.active"), null);

  const single = makeHarness();
  Object.entries({
    "#capture-mode": "SINGLE", "#save-policy": "SAVE_ALL",
    "#trigger-source": "SOFTWARE", "#sync-timeout": "0",
  }).forEach(([selector, value]) => { single.node(selector).value = value; });
  single.run('state.connected = true; state.config = {state: "APPLIED", actual: {profile_sha256: "abc", device_config_crc32: 123}};');
  single.responses.push(
    { payload: { capture_id: "capture-5", acquired_count: 1 } },
    { ok: false },
    { payload: { items: [], next_cursor: null } },
  );
  await single.run("startCapture()");
  assert.equal(single.run("state.active"), null);
}

main().then(() => {
  process.stdout.write("M5 Web task lifecycle: PASS\n");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
