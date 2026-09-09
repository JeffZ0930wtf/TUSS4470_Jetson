"use strict";

const RUN_PLAN_FIELDS = new Set(["loops", "start_delay_ms", "loop_delay_ms", "sweep", "trigger_source", "sync_timeout_ms"]);
const I18N = {
  zh: {
    "app.documentTitle": "TUSS4470 超声采集控制台", "app.title": "超声采集控制台", "app.subtitle": "配置设备并采集未经插值或修改的包络原始数据。",
    "language.aria": "切换到英文", "language.switch": "English",
    "device.label": "设备状态", "device.detecting": "正在检测", "device.waiting": "等待主机服务", "device.offlineDetail": "桥接未连接；仍可编辑、保存和校验草稿", "device.health.unknown": "设备状态未知", "device.health.notDetected": "未检测到设备", "device.health.normal": "设备正常", "device.health.abnormal": "设备异常",
    "activity.idle": "空闲", "activity.configuring": "正在配置", "activity.single": "正在单次采集", "activity.periodic": "正在周期采集", "activity.sweep": "正在参数扫描", "activity.fault": "故障", "backend.simulator": "模拟器", "backend.bridge": "硬件桥接",
    "stages.aria": "采集流程", "stages.draft": "草稿", "stages.validated": "已校验", "stages.applied": "已应用并回读", "stages.captured": "已采集",
    "bank.eyebrow": "设备 + 波形", "bank.title": "参数库", "bank.baseline": "载入 D10×4 基线", "bank.reset": "放弃编辑", "bank.saveDraft": "保存草稿", "bank.validate": "校验", "bank.apply": "应用并回读", "bank.hint": "这里只设置 TUSS4470 设备属性和单帧波形参数；运行次数、间隔和保存策略统一在右侧采集模块设置。",
    "capture.eyebrow": "统一运行入口", "capture.title": "采集", "capture.mode": "采集模式", "capture.savePolicy": "数据保存", "capture.trigger": "触发方式", "capture.syncTimeout": "同步超时（ms）", "capture.stop": "停止", "capture.start.single": "开始单次采集", "capture.start.periodic": "开始周期采集", "capture.start.sweep": "开始参数扫描",
    "mode.single": "单次采集", "mode.periodic": "周期采集", "mode.sweep": "单参数扫描", "save.all": "保存每一次", "save.last": "只保存最后一次", "save.none": "不保存", "trigger.software": "软件触发", "trigger.slave": "外部同步从机", "trigger.master": "外部同步主机",
    "periodic.period": "周期（µs）", "periodic.count": "次数（0 = 无限）", "periodic.lease": "租约（ms）", "periodic.triggerHint": "周期采集由固件内部定时器触发，不使用外部同步设置。", "sweep.field": "扫描参数", "sweep.values": "扫描值（JSON 数组）", "sweep.loops": "每个值采集次数", "sweep.startDelay": "开始延时（ms）", "sweep.loopDelay": "循环间隔（ms）",
    "counter.planned": "计划", "counter.acquired": "已采集", "counter.saved": "已保存", "counter.discarded": "按策略丢弃",
    "waveform.eyebrow": "最近一次", "waveform.title": "原始包络", "waveform.empty": "暂无波形", "waveform.aria": "原始 ADC 波形", "waveform.hint": "显示 2048 个原始 ADC 点；画布缩放不会改变采集值或已保存数据。", "waveform.summary": "{count} 点 · {id}", "waveform.downloadFailed": "原始采样下载失败",
    "history.eyebrow": "SQLite 数据库", "history.title": "已保存记录", "history.refresh": "刷新", "history.more": "加载更早记录", "history.empty": "数据库中暂无已保存采集。", "history.detail": "序号 {sequence} · {count} 点", "history.view": "查看", "history.download": "原始 .u16le",
    "field.draft": "草稿 {value}", "field.requested": "请求值 {value}", "field.actual": "请求 {requested} · 实际 {actual}", "field.readback": "请求 {requested} · 回读 {readback}", "field.applied": "请求 {value} · 已应用", "field.invalidJson": "{field} 必须是有效 JSON", "field.semantic": "语义参数",
    "message.baselineLoaded": "D10×4 基线已载入草稿", "message.validationPassed": "配置校验通过", "message.draftSaved": "草稿已保存", "message.applied": "配置已应用并完成回读", "message.noDevice": "未检测到设备，不能执行硬件操作", "message.applyFirst": "请先应用并回读配置", "message.sweepArray": "扫描值必须是 JSON 数组",
    "capture.status.idle": "空闲", "capture.status.singleRunning": "正在单次采集", "capture.status.periodicRunning": "正在周期采集", "capture.status.sweepRunning": "正在参数扫描", "capture.status.stopping": "正在停止", "capture.status.singleComplete": "单次采集完成", "capture.status.progress": "{state} · 已采集 {count}",
    "session.running": "运行中", "session.stopping": "正在停止", "session.completed": "已完成", "session.stopped": "已停止", "session.failed": "失败", "session.interrupted": "已中断"
  },
  en: {
    "app.documentTitle": "TUSS4470 Ultrasonic Acquisition Console", "app.title": "Ultrasonic Acquisition Console", "app.subtitle": "Configure the device and acquire raw envelope samples without interpolation or modification.",
    "language.aria": "Switch to Chinese", "language.switch": "中文",
    "device.label": "Device status", "device.detecting": "Detecting", "device.waiting": "Waiting for host service", "device.offlineDetail": "Bridge disconnected; drafts can still be edited, saved, and validated", "device.health.unknown": "Unknown device status", "device.health.notDetected": "Device not detected", "device.health.normal": "Device ready", "device.health.abnormal": "Device fault",
    "activity.idle": "Idle", "activity.configuring": "Applying configuration", "activity.single": "Single capture running", "activity.periodic": "Periodic capture running", "activity.sweep": "Parameter sweep running", "activity.fault": "Fault", "backend.simulator": "Simulator", "backend.bridge": "Hardware bridge",
    "stages.aria": "Acquisition workflow", "stages.draft": "Draft", "stages.validated": "Validated", "stages.applied": "Applied and read back", "stages.captured": "Captured",
    "bank.eyebrow": "Device + waveform", "bank.title": "Parameter bank", "bank.baseline": "Load D10×4 baseline", "bank.reset": "Discard edits", "bank.saveDraft": "Save draft", "bank.validate": "Validate", "bank.apply": "Apply and read back", "bank.hint": "Set TUSS4470 device properties and single-frame waveform parameters here. Configure run count, timing, and save policy in the acquisition panel.",
    "capture.eyebrow": "Unified run control", "capture.title": "Acquisition", "capture.mode": "Acquisition mode", "capture.savePolicy": "Data retention", "capture.trigger": "Trigger source", "capture.syncTimeout": "Sync timeout (ms)", "capture.stop": "Stop", "capture.start.single": "Start single capture", "capture.start.periodic": "Start periodic capture", "capture.start.sweep": "Start parameter sweep",
    "mode.single": "Single capture", "mode.periodic": "Periodic capture", "mode.sweep": "Single-parameter sweep", "save.all": "Save every capture", "save.last": "Save last capture only", "save.none": "Do not save", "trigger.software": "Software trigger", "trigger.slave": "External sync slave", "trigger.master": "External sync master",
    "periodic.period": "Period (µs)", "periodic.count": "Count (0 = unlimited)", "periodic.lease": "Lease (ms)", "periodic.triggerHint": "Periodic acquisition uses the firmware's internal timer; external synchronization does not apply.", "sweep.field": "Sweep parameter", "sweep.values": "Sweep values (JSON array)", "sweep.loops": "Captures per value", "sweep.startDelay": "Start delay (ms)", "sweep.loopDelay": "Loop interval (ms)",
    "counter.planned": "Planned", "counter.acquired": "Acquired", "counter.saved": "Saved", "counter.discarded": "Discarded by policy",
    "waveform.eyebrow": "Latest capture", "waveform.title": "Raw envelope", "waveform.empty": "No waveform", "waveform.aria": "Raw ADC waveform", "waveform.hint": "Displays all 2048 raw ADC samples. Canvas scaling does not alter acquired or stored values.", "waveform.summary": "{count} samples · {id}", "waveform.downloadFailed": "Raw sample download failed",
    "history.eyebrow": "SQLite database", "history.title": "Saved captures", "history.refresh": "Refresh", "history.more": "Load earlier records", "history.empty": "No saved captures in the database.", "history.detail": "Sequence {sequence} · {count} samples", "history.view": "View", "history.download": "Raw .u16le",
    "field.draft": "Draft {value}", "field.requested": "Requested {value}", "field.actual": "Requested {requested} · actual {actual}", "field.readback": "Requested {requested} · read back {readback}", "field.applied": "Requested {value} · applied", "field.invalidJson": "{field} must be valid JSON", "field.semantic": "semantic",
    "message.baselineLoaded": "D10×4 baseline loaded into draft", "message.validationPassed": "Configuration is valid", "message.draftSaved": "Draft saved", "message.applied": "Configuration applied and read back", "message.noDevice": "No device detected; hardware operations are unavailable", "message.applyFirst": "Apply and read back the configuration first", "message.sweepArray": "Sweep values must be a JSON array",
    "capture.status.idle": "Idle", "capture.status.singleRunning": "Single capture running", "capture.status.periodicRunning": "Periodic capture running", "capture.status.sweepRunning": "Parameter sweep running", "capture.status.stopping": "Stopping", "capture.status.singleComplete": "Single capture complete", "capture.status.progress": "{state} · {count} acquired",
    "session.running": "Running", "session.stopping": "Stopping", "session.completed": "Completed", "session.stopped": "Stopped", "session.failed": "Failed", "session.interrupted": "Interrupted"
  }
};
const DEVICE_HEALTH_LABELS = { NOT_DETECTED: "device.health.notDetected", NORMAL: "device.health.normal", ABNORMAL: "device.health.abnormal" };
const ACTIVITY_LABELS = { IDLE: "activity.idle", CONFIGURING: "activity.configuring", CAPTURING_SINGLE: "activity.single", CAPTURING_PERIODIC: "activity.periodic", SWEEPING: "activity.sweep", FAULT: "activity.fault" };
const BACKEND_LABELS = { SIMULATOR: "backend.simulator", BRIDGE: "backend.bridge" };
const SESSION_STATE_LABELS = { RUNNING: "session.running", STOPPING: "session.stopping", COMPLETED: "session.completed", STOPPED: "session.stopped", FAILED: "session.failed", INTERRUPTED: "session.interrupted" };
const storedLanguage = localStorage.getItem("usac-language");
const state = { schema: null, config: null, etag: null, edits: {}, connected: false, active: null, historyCursor: null, historyItems: [], language: storedLanguage === "en" ? "en" : "zh", devicePayload: null, counterPayload: {}, captureStatusKey: "capture.status.idle", captureStatusValues: {}, waveformSummary: null, lastRenderedCaptureId: null };
const $ = (selector) => document.querySelector(selector);

function t(key, values = {}) {
  const template = I18N[state.language][key] || I18N.zh[key] || key;
  return Object.entries(values).reduce((text, [name, value]) => text.replaceAll(`{${name}}`, String(value)), template);
}

function applyStaticTranslations() {
  document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
  document.title = t("app.documentTitle");
  document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => { node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel)); });
  $("#language-toggle").textContent = t("language.switch");
  if (!state.devicePayload) {
    $("#device-state").textContent = t("device.detecting");
    $("#device-detail").textContent = t("device.waiting");
  }
  if (!state.waveformSummary) $("#sample-label").textContent = t("waveform.empty");
}

function setCaptureStatus(key, values = {}) {
  state.captureStatusKey = key; state.captureStatusValues = values;
  const displayValues = { ...values };
  if (displayValues.stateKey) displayValues.state = t(displayValues.stateKey);
  $("#capture-status").textContent = t(key, displayValues);
}

function setLanguage(language) {
  state.language = language === "en" ? "en" : "zh";
  localStorage.setItem("usac-language", state.language);
  applyStaticTranslations(); updateMode();
  if (state.schema && state.config) renderParameters();
  if (state.devicePayload) updateDevice(state.devicePayload);
  renderCounters(state.counterPayload); renderHistory();
  setCaptureStatus(state.captureStatusKey, state.captureStatusValues);
  if (state.waveformSummary) $("#sample-label").textContent = t("waveform.summary", state.waveformSummary);
  else $("#sample-label").textContent = t("waveform.empty");
}

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

function setHardwareActions() {
  $("#apply-button").disabled = !state.connected || Boolean(state.active);
  $("#capture-start").disabled = !state.connected || Boolean(state.active);
  $("#capture-stop").disabled = !state.active || state.active.mode === "SINGLE";
}

function updateDevice(payload) {
  const wasConnected = state.connected;
  state.devicePayload = payload;
  state.connected = Boolean(payload.connected);
  $("#device-state").textContent = t(DEVICE_HEALTH_LABELS[payload.health] || "device.health.unknown");
  $("#device-dot").className = `status-dot ${payload.health === "NORMAL" ? "ok" : payload.health === "ABNORMAL" ? "fault" : ""}`;
  if (!payload.connected) {
    $("#device-detail").textContent = t("device.offlineDetail");
  } else {
    const firmware = payload.firmware;
    const activity = t(ACTIVITY_LABELS[payload.activity] || payload.activity);
    const backend = t(BACKEND_LABELS[payload.backend] || payload.backend);
    $("#device-detail").textContent = `${backend} · ${activity} · ${payload.device_id.slice(0, 8)} · FW ${firmware.major}.${firmware.minor}.${firmware.patch}+${firmware.build}`;
  }
  setHardwareActions();
  if (wasConnected && !state.connected && state.config?.state === "APPLIED") {
    loadConfig().catch((error) => toast(error.message));
  }
}

async function refreshDevice() {
  const { payload } = await fetchJson("/api/v1/device");
  updateDevice(payload);
  window.setTimeout(() => refreshDevice().catch(() => window.setTimeout(refreshDevice, 1500)), 1000);
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
      try { next = JSON.parse(control.value); } catch (_error) { toast(t("field.invalidJson", { field: field.name })); return; }
    } else next = control.value;
    state.edits[field.name] = next;
    const row = control.closest(".field-row"); row.classList.add("edited");
    row.querySelector(".field-state").textContent = t("field.draft", { value: JSON.stringify(next) });
    stage("draft");
  });
  return control;
}

function fieldState(field, value) {
  if (Object.hasOwn(state.edits, field.name)) return t("field.draft", { value: JSON.stringify(value) });
  if (state.config.state !== "APPLIED") return t("field.requested", { value: JSON.stringify(value) });
  const actualNames = { requested_burst_frequency_hz: "burst_frequency_hz", requested_sample_rate_hz: "sample_rate_hz", requested_record_ms: "record_ms" };
  const actualName = actualNames[field.name] || field.name;
  if (Object.hasOwn(state.config.actual, actualName)) return t("field.actual", { requested: JSON.stringify(value), actual: JSON.stringify(state.config.actual[actualName]) });
  if (state.config.readback.fields && Object.hasOwn(state.config.readback.fields, field.name)) return t("field.readback", { requested: JSON.stringify(value), readback: JSON.stringify(state.config.readback.fields[field.name]) });
  return t("field.applied", { value: JSON.stringify(value) });
}

function visibleParameterFields() {
  return state.schema.fields.filter((field) => !RUN_PLAN_FIELDS.has(field.name));
}

function renderParameters() {
  const root = $("#parameter-groups"); root.replaceChildren();
  const fieldsToRender = visibleParameterFields();
  const groups = new Map();
  fieldsToRender.forEach((field) => { if (!groups.has(field.group)) groups.set(field.group, []); groups.get(field.group).push(field); });
  groups.forEach((fields, groupName) => {
    const section = document.createElement("section"); section.className = "parameter-group";
    const heading = document.createElement("h3"); heading.textContent = groupName; section.append(heading);
    fields.forEach((field) => {
      const row = document.createElement("div"); row.className = "field-row";
      const label = document.createElement("div"); label.className = "field-label";
      const name = document.createElement("strong"); name.textContent = field.name;
      const unit = document.createElement("small"); unit.textContent = `${field.unit} · ${field.safety || field.access || t("field.semantic")}`;
      const value = Object.hasOwn(state.edits, field.name) ? state.edits[field.name] : state.config.requested[field.name];
      const status = document.createElement("small"); status.className = "field-state"; status.textContent = fieldState(field, value);
      label.append(name, unit); row.append(label, controlFor(field, value), status); section.append(row);
    });
    root.append(section);
  });
  const sweep = $("#sweep-field"); const selected = sweep.value; sweep.replaceChildren();
  fieldsToRender.filter((field) => field.sweepable).forEach((field) => sweep.add(new Option(field.name, field.name)));
  if ([...sweep.options].some((option) => option.value === selected)) sweep.value = selected;
}

function loadBaseline() {
  const derived = new Set(["burst_period_ticks", "sample_interval_ticks", "sample_count", "requested_record_ms"]);
  state.edits = {};
  visibleParameterFields().forEach((field) => {
    if (!field.read_only && !derived.has(field.name) && Object.hasOwn(field, "default")) state.edits[field.name] = field.default;
  });
  renderParameters(); stage("draft"); toast(t("message.baselineLoaded"));
}

async function loadConfig() {
  const { payload, response } = await fetchJson("/api/v1/config");
  state.config = payload; state.etag = response.headers.get("etag"); state.edits = {};
  renderParameters(); stage(payload.state === "APPLIED" ? "applied" : "draft"); setHardwareActions();
}

function showValidation(payload) {
  const box = $("#validation");
  if (!payload.errors.length) { box.hidden = true; stage("validated"); toast(t("message.validationPassed")); return; }
  box.textContent = payload.errors.map((item) => `${item.field}: ${item.message}`).join("\n"); box.hidden = false;
}

async function validateConfig() {
  const { payload } = await fetchJson("/api/v1/config/validate", { method: "POST", body: JSON.stringify({ changes: state.edits }) });
  showValidation(payload);
}

async function saveDraft() {
  const { payload } = await fetchJson("/api/v1/config", { method: "PATCH", body: JSON.stringify({ changes: state.edits }) });
  state.config = payload; state.edits = {}; renderParameters(); stage("draft"); toast(t("message.draftSaved"));
}

async function applyConfig() {
  const { payload, response } = await fetchJson("/api/v1/config", { method: "PUT", headers: { "If-Match": state.etag }, body: JSON.stringify({ changes: state.edits }) });
  state.config = payload; state.etag = response.headers.get("etag"); state.edits = {}; renderParameters(); stage("applied"); toast(t("message.applied"));
}

function identity() {
  if (!state.connected) throw new Error(t("message.noDevice"));
  if (state.config.state !== "APPLIED") throw new Error(t("message.applyFirst"));
  return { expected_profile_sha256: state.config.actual.profile_sha256, expected_device_config_crc32: state.config.actual.device_config_crc32 };
}

function savePolicy() { return { save_policy: $("#save-policy").value }; }
function triggerOptions() { return { trigger_source: $("#trigger-source").value, sync_timeout_ms: Number($("#sync-timeout").value) }; }

function renderCounters(payload = {}) {
  state.counterPayload = payload;
  const values = [payload.requested_count ?? "—", payload.acquired_count ?? 0, payload.saved_count ?? 0, payload.discarded_by_policy_count ?? 0];
  $("#capture-counters").querySelectorAll("strong").forEach((node, index) => { node.textContent = values[index]; });
}

function updateMode() {
  const mode = $("#capture-mode").value;
  $("#periodic-fields").hidden = mode !== "PERIODIC";
  $("#sweep-fields").hidden = mode !== "SWEEP";
  const triggerApplies = mode !== "PERIODIC";
  $("#trigger-fields").hidden = !triggerApplies;
  $("#trigger-source").disabled = !triggerApplies;
  $("#sync-timeout").disabled = !triggerApplies;
  $("#periodic-trigger-hint").hidden = triggerApplies;
  $("#capture-start").textContent = t({ SINGLE: "capture.start.single", PERIODIC: "capture.start.periodic", SWEEP: "capture.start.sweep" }[mode]);
}

async function drawCapture(captureId) {
  const response = await fetch(`/api/v1/captures/${captureId}/samples`); if (!response.ok) throw new Error(t("waveform.downloadFailed"));
  const bytes = new Uint8Array(await response.arrayBuffer()); const values = new Uint16Array(bytes.length / 2);
  for (let index = 0; index < values.length; index += 1) values[index] = bytes[index * 2] | (bytes[index * 2 + 1] << 8);
  const canvas = $("#waveform"); const context = canvas.getContext("2d"); context.clearRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "#58a6ff"; context.lineWidth = 1.4; context.beginPath(); const max = Math.max(...values, 1);
  values.forEach((value, index) => { const x = index * (canvas.width - 1) / (values.length - 1); const y = canvas.height - 10 - value * (canvas.height - 20) / max; index ? context.lineTo(x, y) : context.moveTo(x, y); });
  context.stroke(); state.waveformSummary = { count: values.length, id: captureId.slice(0, 8) }; $("#sample-label").textContent = t("waveform.summary", state.waveformSummary);
}

function renderHistory() {
  const root = $("#capture-history"); root.replaceChildren();
  if (!state.historyItems.length) { root.textContent = t("history.empty"); return; }
  state.historyItems.forEach((item) => {
    const row = document.createElement("div"); row.className = "history-row";
    const meta = document.createElement("div"); meta.className = "history-meta";
    const name = document.createElement("strong"); name.textContent = item.capture_id.slice(0, 8);
    const detail = document.createElement("small"); detail.textContent = t("history.detail", { sequence: item.capture_sequence, count: item.sample_count });
    meta.append(name, detail);
    const actions = document.createElement("div"); actions.className = "history-actions";
    const view = document.createElement("button"); view.className = "quiet"; view.textContent = t("history.view");
    view.addEventListener("click", () => drawCapture(item.capture_id).catch((error) => toast(error.message)));
    const download = document.createElement("a"); download.textContent = t("history.download"); download.href = `/api/v1/captures/${item.capture_id}/samples`; download.download = `${item.capture_id}.u16le`;
    actions.append(view, download); row.append(meta, actions); root.append(row);
  });
}

async function loadHistory(reset = true) {
  const parameters = new URLSearchParams({ limit: "20" });
  if (!reset && state.historyCursor) parameters.set("cursor", state.historyCursor);
  const query = parameters.toString();
  const { payload } = await fetchJson(`/api/v1/captures?${query}`);
  state.historyItems = reset ? payload.items : state.historyItems.concat(payload.items); state.historyCursor = payload.next_cursor;
  renderHistory(); $("#history-more").hidden = !state.historyCursor;
}

function scheduleSessionPoll(sessionId) {
  if (state.active?.session_id === sessionId) window.setTimeout(() => pollSession(), 250);
}

async function refreshLatestWaveform(payload) {
  const captureId = payload.last_capture_id;
  if (!captureId || captureId === state.lastRenderedCaptureId) return;
  try {
    await drawCapture(captureId);
    state.lastRenderedCaptureId = captureId;
  } catch (error) {
    toast(error.message);
  }
}

async function pollSession() {
  const active = state.active;
  if (!active?.session_id) return;
  try {
    const { payload } = await fetchJson(`/api/v1/sessions/${active.session_id}`);
    if (state.active?.session_id !== active.session_id) return;
    renderCounters(payload); setCaptureStatus("capture.status.progress", { stateKey: SESSION_STATE_LABELS[payload.state] || payload.state, count: payload.acquired_count });
    if (["COMPLETED", "STOPPED", "FAILED", "INTERRUPTED"].includes(payload.state)) {
      state.active = null;
      setHardwareActions();
      await refreshLatestWaveform(payload);
      await loadHistory(true).catch((error) => toast(error.message));
      return;
    }
    await refreshLatestWaveform(payload);
  } catch (error) {
    toast(error.message);
  } finally {
    scheduleSessionPoll(active.session_id);
  }
}

async function startCapture() {
  const mode = $("#capture-mode").value;
  const common = { ...identity(), ...savePolicy() };
  if (mode === "SINGLE") {
    state.active = { mode: "SINGLE" }; setCaptureStatus("capture.status.singleRunning"); setHardwareActions();
    let payload;
    try {
      ({ payload } = await fetchJson("/api/v1/captures", { method: "POST", body: JSON.stringify({ ...common, ...triggerOptions() }) }));
      renderCounters(payload);
    } finally {
      state.active = null;
      setHardwareActions();
    }
    await refreshLatestWaveform({ last_capture_id: payload.capture_id });
    await loadHistory(true).catch((error) => toast(error.message));
    stage("captured"); setCaptureStatus("capture.status.singleComplete"); toast(t("capture.status.singleComplete")); return;
  }
  let endpoint; let body;
  if (mode === "PERIODIC") {
    endpoint = "/api/v1/periodic/start";
    body = { ...common, period_us: Number($("#period-us").value), capture_count: Number($("#periodic-count").value), lease_timeout_ms: Number($("#lease-timeout").value) };
  } else {
    let values;
    try { values = JSON.parse($("#sweep-values").value); } catch (_error) { throw new Error(t("message.sweepArray")); }
    if (!Array.isArray(values)) throw new Error(t("message.sweepArray"));
    endpoint = "/api/v1/sweeps";
    body = { ...common, ...triggerOptions(), field: $("#sweep-field").value, values, loops: Number($("#sweep-loops").value), start_delay_ms: Number($("#sweep-start-delay").value), loop_delay_ms: Number($("#sweep-delay").value) };
  }
  state.lastRenderedCaptureId = null;
  state.active = { mode, ...(await fetchJson(endpoint, { method: "POST", body: JSON.stringify(body) })).payload };
  renderCounters(state.active); setCaptureStatus(mode === "PERIODIC" ? "capture.status.periodicRunning" : "capture.status.sweepRunning"); setHardwareActions(); pollSession();
}

async function stopCapture() {
  if (!state.active) return;
  if (state.active.mode === "PERIODIC") {
    await fetchJson("/api/v1/periodic/stop", { method: "POST", body: JSON.stringify({ session_id: state.active.session_id, schedule_id: state.active.schedule_id }) });
  } else {
    await fetchJson(`/api/v1/sweeps/${state.active.session_id}/stop`, { method: "POST" });
  }
  setCaptureStatus("capture.status.stopping");
}

function bindActions() {
  const guarded = (operation) => () => operation().catch((error) => { setHardwareActions(); toast(error.message); });
  $("#baseline-button").addEventListener("click", loadBaseline); $("#reset-button").addEventListener("click", guarded(loadConfig));
  $("#save-draft-button").addEventListener("click", guarded(saveDraft)); $("#validate-button").addEventListener("click", guarded(validateConfig));
  $("#apply-button").addEventListener("click", guarded(applyConfig)); $("#capture-mode").addEventListener("change", updateMode);
  $("#language-toggle").addEventListener("click", () => setLanguage(state.language === "zh" ? "en" : "zh"));
  $("#capture-start").addEventListener("click", guarded(startCapture)); $("#capture-stop").addEventListener("click", guarded(stopCapture));
  $("#history-refresh").addEventListener("click", guarded(() => loadHistory(true))); $("#history-more").addEventListener("click", guarded(() => loadHistory(false)));
}

async function init() {
  applyStaticTranslations(); bindActions(); updateMode(); setCaptureStatus("capture.status.idle");
  const schema = await fetchJson("/api/v1/config/schema"); state.schema = schema.payload;
  await Promise.all([loadConfig(), loadHistory(true), refreshDevice()]);
}

init().catch((error) => toast(error.message));
