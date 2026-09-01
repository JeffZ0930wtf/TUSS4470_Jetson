"use strict";

const state = { schema: null, config: null, etag: null, edits: {}, periodic: null, sweep: null };
const $ = (selector) => document.querySelector(selector);

async function fetchJson(path, options = {}) {
  const { headers = {}, ...requestOptions } = options;
  const response = await fetch(path, { ...requestOptions, headers: { "Content-Type": "application/json", ...headers } });
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail));
  return { payload, response };
}

function toast(message) {
  const node = $("#toast"); node.textContent = message; node.hidden = false;
  window.setTimeout(() => { node.hidden = true; }, 3500);
}

function stage(name) {
  document.querySelectorAll(".signal-strip span").forEach((node) => node.classList.toggle("active", node.dataset.stage === name));
}

function controlFor(field, value) {
  let control;
  if (field.kind === "enum") {
    control = document.createElement("select");
    field.values.forEach((item) => control.add(new Option(item, item)));
    control.value = value;
  } else if (field.kind === "bool") {
    control = document.createElement("input"); control.type = "checkbox"; control.checked = Boolean(value);
  } else if (field.kind === "object") {
    control = document.createElement("textarea"); control.rows = 2; control.value = JSON.stringify(value);
  } else {
    control = document.createElement("input"); control.type = "number"; control.min = field.minimum; control.max = field.maximum; control.value = value;
  }
  control.disabled = field.read_only; control.dataset.field = field.name;
  control.addEventListener(field.kind === "object" ? "change" : "input", () => {
    let next;
    if (field.kind === "bool") next = control.checked;
    else if (["uint", "integer", "number", "constant"].includes(field.kind)) next = Number(control.value);
    else if (field.kind === "object") {
      try { next = JSON.parse(control.value); } catch (_error) { toast(`${field.name} must contain valid JSON`); return; }
    } else next = control.value;
    state.edits[field.name] = next;
    control.closest(".field-row").classList.add("edited"); stage("draft");
  });
  return control;
}

function renderParameters() {
  const root = $("#parameter-groups"); root.replaceChildren();
  const groups = new Map();
  state.schema.fields.forEach((field) => { if (!groups.has(field.group)) groups.set(field.group, []); groups.get(field.group).push(field); });
  groups.forEach((fields, groupName) => {
    const section = document.createElement("section"); section.className = "parameter-group";
    const heading = document.createElement("h3"); heading.textContent = groupName; section.append(heading);
    fields.forEach((field) => {
      const row = document.createElement("div"); row.className = "field-row";
      const label = document.createElement("div"); label.className = "field-label";
      const name = document.createElement("strong"); name.textContent = field.name;
      const unit = document.createElement("small"); unit.textContent = `${field.unit} · ${field.safety || field.access || "semantic"}`;
      label.append(name, unit); row.append(label, controlFor(field, state.config.requested[field.name])); section.append(row);
    });
    root.append(section);
  });
  const sweep = $("#sweep-field"); sweep.replaceChildren();
  state.schema.fields.filter((field) => field.sweepable).forEach((field) => sweep.add(new Option(field.name, field.name)));
}

async function loadConfig() {
  const { payload, response } = await fetchJson("/api/v1/config");
  state.config = payload; state.etag = response.headers.get("etag"); state.edits = {};
  renderParameters(); stage(payload.state === "APPLIED" ? "applied" : "draft");
}

function showValidation(payload) {
  const box = $("#validation");
  if (!payload.errors.length) { box.hidden = true; stage("validated"); toast("Configuration is valid"); return; }
  box.textContent = payload.errors.map((item) => `${item.field}: ${item.message}`).join("\n"); box.hidden = false;
}

async function validateConfig() {
  const { payload } = await fetchJson("/api/v1/config/validate", { method: "POST", body: JSON.stringify({ changes: state.edits }) });
  showValidation(payload);
}

async function applyConfig() {
  const { payload, response } = await fetchJson("/api/v1/config", { method: "PUT", headers: { "If-Match": state.etag }, body: JSON.stringify({ changes: state.edits }) });
  state.config = payload; state.etag = response.headers.get("etag"); state.edits = {}; renderParameters(); stage("applied"); toast("Applied and read back");
}

function identity() {
  if (state.config.state !== "APPLIED") throw new Error("Apply and read back a configuration first");
  return { expected_profile_sha256: state.config.actual.profile_sha256, expected_device_config_crc32: state.config.actual.device_config_crc32 };
}

async function captureOnce() {
  const body = { ...identity(), trigger_source: $("#trigger-source").value, sync_timeout_ms: Number($("#sync-timeout").value) };
  const { payload } = await fetchJson("/api/v1/captures", { method: "POST", body: JSON.stringify(body) });
  await drawCapture(payload.capture_id); stage("captured"); toast(`Committed capture ${payload.capture_id.slice(0, 8)}`);
}

async function drawCapture(captureId) {
  const response = await fetch(`/api/v1/captures/${captureId}/samples`); if (!response.ok) throw new Error("Raw sample download failed");
  const bytes = new Uint8Array(await response.arrayBuffer()); const values = new Uint16Array(bytes.length / 2);
  for (let index = 0; index < values.length; index += 1) values[index] = bytes[index * 2] | (bytes[index * 2 + 1] << 8);
  const canvas = $("#waveform"); const context = canvas.getContext("2d"); context.clearRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "#58a6ff"; context.lineWidth = 1.4; context.beginPath(); const max = Math.max(...values, 1);
  values.forEach((value, index) => { const x = index * (canvas.width - 1) / (values.length - 1); const y = canvas.height - 10 - value * (canvas.height - 20) / max; index ? context.lineTo(x, y) : context.moveTo(x, y); });
  context.stroke(); $("#sample-label").textContent = `${values.length} points · ${captureId.slice(0, 8)}`;
}

async function pollSession(kind) {
  const active = state[kind]; if (!active) return;
  const { payload } = await fetchJson(`/api/v1/sessions/${active.session_id}`);
  $(`#${kind}-status`).textContent = `${payload.state} · ${payload.capture_count} captures`;
  if (["COMPLETED", "STOPPED", "FAILED"].includes(payload.state)) {
    if (payload.capture_ids.length) await drawCapture(payload.capture_ids.at(-1));
    state[kind] = null; $(`#${kind}-stop`).disabled = true; $(`#${kind}-start`).disabled = false; return;
  }
  window.setTimeout(() => pollSession(kind).catch((error) => toast(error.message)), 250);
}

async function startPeriodic() {
  const body = { ...identity(), period_us: Number($("#period-us").value), capture_count: Number($("#periodic-count").value), lease_timeout_ms: Number($("#lease-timeout").value) };
  state.periodic = (await fetchJson("/api/v1/periodic/start", { method: "POST", body: JSON.stringify(body) })).payload;
  $("#periodic-start").disabled = true; $("#periodic-stop").disabled = false; pollSession("periodic");
}

async function stopPeriodic() {
  const body = { session_id: state.periodic.session_id, schedule_id: state.periodic.schedule_id };
  await fetchJson("/api/v1/periodic/stop", { method: "POST", body: JSON.stringify(body) });
}

async function startSweep() {
  const values = JSON.parse($("#sweep-values").value); if (!Array.isArray(values)) throw new Error("Sweep values must be a JSON array");
  const body = { ...identity(), field: $("#sweep-field").value, values, loops: Number($("#sweep-loops").value), start_delay_ms: 0, loop_delay_ms: Number($("#sweep-delay").value), trigger_source: $("#trigger-source").value, sync_timeout_ms: Number($("#sync-timeout").value) };
  state.sweep = (await fetchJson("/api/v1/sweeps", { method: "POST", body: JSON.stringify(body) })).payload;
  $("#sweep-start").disabled = true; $("#sweep-stop").disabled = false; pollSession("sweep");
}

async function stopSweep() { await fetchJson(`/api/v1/sweeps/${state.sweep.session_id}/stop`, { method: "POST" }); }

function bindActions() {
  const guarded = (operation) => () => operation().catch((error) => toast(error.message));
  $("#reset-button").addEventListener("click", guarded(loadConfig));
  $("#validate-button").addEventListener("click", guarded(validateConfig));
  $("#apply-button").addEventListener("click", guarded(applyConfig));
  $("#capture-button").addEventListener("click", guarded(captureOnce));
  $("#periodic-start").addEventListener("click", guarded(startPeriodic)); $("#periodic-stop").addEventListener("click", guarded(stopPeriodic));
  $("#sweep-start").addEventListener("click", guarded(startSweep)); $("#sweep-stop").addEventListener("click", guarded(stopSweep));
}

async function init() {
  bindActions();
  const [schema, device] = await Promise.all([fetchJson("/api/v1/config/schema"), fetchJson("/api/v1/device")]);
  state.schema = schema.payload; $("#device-state").textContent = `State ${device.payload.status.device_state}`; $("#device-dot").classList.add("ok");
  await loadConfig();
}

init().catch((error) => toast(error.message));
