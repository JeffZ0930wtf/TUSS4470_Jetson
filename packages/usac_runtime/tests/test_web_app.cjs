"use strict";

// Execute the repository's actual controller functions with a deliberately
// small DOM/HTTP stub. This verifies task ownership without launching a server.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const sourcePath = path.join(__dirname, "..", "src", "usac_runtime", "web", "app.js");
const source = fs.readFileSync(sourcePath, "utf8")
  .replace(/init\(\)\.catch\(\(error\) => toast\(error\.message\)\);\s*$/, "");
const htmlPath = path.join(__dirname, "..", "src", "usac_runtime", "web", "index.html");
const html = fs.readFileSync(htmlPath, "utf8");

function staticAttributeNodes(attribute, datasetKey) {
  const tagPattern = /<[a-z][^>]*>/gi;
  const attributePattern = new RegExp(`\\s${attribute}\\s*=\\s*(["'])(.*?)\\1`, "i");
  return [...html.matchAll(tagPattern)].flatMap(([tag]) => {
    const match = tag.match(attributePattern);
    if (!match) return [];
    return [{
      dataset: { [datasetKey]: match[2] },
      textContent: "",
      attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; },
    }];
  });
}

function makeHarness() {
  const nodes = new Map();
  const counters = Array.from({ length: 4 }, () => ({ textContent: "" }));
  const staticTextNodes = staticAttributeNodes("data-i18n", "i18n");
  const staticAriaNodes = staticAttributeNodes("data-i18n-aria-label", "i18nAriaLabel");
  const requests = [];
  const timers = [];
  const responses = [];
  const canvasOps = [];

  function node(selector) {
    if (!nodes.has(selector)) {
      nodes.set(selector, {
        value: "",
        disabled: false,
        hidden: false,
        open: false,
        textContent: "",
        className: "",
        dataset: {},
        children: [],
        listeners: {},
        addEventListener(event, handler) { this.listeners[event] = handler; },
        append(...children) { this.children.push(...children); },
        setAttribute(name, value) { this[name] = value; },
        showModal() { this.open = true; },
        close() { this.open = false; this.listeners.close?.(); },
        focus() {},
        querySelectorAll() { return selector === "#capture-counters" ? counters : []; },
        replaceChildren(...children) { this.children = children; },
        getContext() {
          return {
            clearRect(...args) { canvasOps.push(["clearRect", ...args]); },
            beginPath() { canvasOps.push(["beginPath"]); },
            moveTo(...args) { canvasOps.push(["moveTo", ...args]); },
            lineTo(...args) { canvasOps.push(["lineTo", ...args]); },
            arc(...args) { canvasOps.push(["arc", ...args]); },
            stroke() { canvasOps.push(["stroke"]); },
            fill() { canvasOps.push(["fill"]); },
            fillText(...args) { canvasOps.push(["fillText", ...args, this.fillStyle, this.font]); },
            save() {}, restore() {}, setTransform() {},
            strokeStyle: "", fillStyle: "", lineWidth: 0, font: "",
          };
        },
      });
    }
    return nodes.get(selector);
  }

  const sandbox = {
    console,
    document: {
      documentElement: {}, querySelector: node,
      querySelectorAll(selector) {
        if (selector === "[data-i18n]") return staticTextNodes;
        if (selector === "[data-i18n-aria-label]") return staticAriaNodes;
        return [];
      },
      createElement: (tagName) => ({
        tagName, className: "", textContent: "", checked: false, disabled: false,
        dataset: {}, listeners: {}, children: [], style: {},
        addEventListener(event, handler) { this.listeners[event] = handler; },
        append(...children) { this.children.push(...children); },
        setAttribute(name, value) { this[name] = value; },
      }),
    },
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
        status: response.status ?? (response.ok === false ? 500 : 200),
        headers: { get: () => null },
        json: async () => response.payload ?? {},
        arrayBuffer: async () => Uint8Array.from(response.bytes ?? [1, 0, 2, 0]).buffer,
      };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return {
    node, requests, responses, timers, canvasOps, staticTextNodes, staticAriaNodes,
    run: (code) => vm.runInContext(code, sandbox),
  };
}

async function checkHistoryUsesFreshGroupingMetadata() {
  const harness = makeHarness();
  harness.run(`
    state.experiments = [{experiment_id:"exp-a", name:"Old experiment"}];
    state.groupsByExperiment.set("exp-a", [{group_id:"group-a", name:"Old group", cell_id:"Old cell"}]);
    bindActions();
  `);
  harness.responses.push({payload: {items: [{
    capture_id: "archived-1", capture_sequence: 1, sample_count: 2048,
    grouping_metadata: {experiment_id:"exp-a", group_id:"group-a", experiment_name:"New experiment", group_name:"New group", cell_id:null},
  }], next_cursor: null}});
  await harness.node("#history-refresh").listeners.click();
  assert.equal(harness.node("#capture-history").children[0].children[0].children[2].textContent,
    "New experiment · New group", "a refreshed row uses fresh API metadata, including cleared cell IDs");
}

async function checkGroupingDialog() {
  const harness = makeHarness();
  const experiment = {experiment_id: "exp-a", name: "Tank A", notes: "Original experiment note"};
  const group = {group_id: "group-a", experiment_id: "exp-a", name: "Run 1", cell_id: "C-42", notes: "Original group note", archived_count: 2};
  harness.run("bindActions(); renderGroupingControls()");
  const dialog = harness.node("#grouping-dialog");
  const click = (id) => harness.node(`#${id}`).listeners.click();
  const submit = () => harness.node("#grouping-form").listeners.submit({preventDefault() {}});

  click("experiment-new");
  assert.equal(dialog.open, true, "New experiment opens its modal editor");
  assert.equal(harness.node("#experiment-edit").disabled, true);
  assert.equal(harness.node("#group-new").disabled, true);
  assert.equal(harness.node("#group-edit").disabled, true);
  assert.equal(harness.node("#grouping-dialog-title").textContent, "新建实验");
  assert.equal(harness.node("#group-fields").hidden, true);
  assert.equal(harness.node("#experiment-name").value, "");
  harness.node("#experiment-name").value = "  ";
  await submit();
  assert.equal(harness.requests.length, 0, "blank names must not send a request");
  assert.match(harness.node("#grouping-error").textContent, /名称必填/);
  harness.node("#experiment-name").value = "unsaved";
  click("grouping-cancel");
  assert.equal(dialog.open, false);
  assert.equal(harness.requests.length, 0, "cancel never writes");

  click("experiment-new");
  assert.equal(harness.node("#experiment-name").value, "");
  harness.node("#experiment-name").value = `  ${experiment.name}  `;
  harness.node("#experiment-notes").value = experiment.notes;
  harness.responses.push({payload: experiment}, {payload: {items: []}});
  await submit();
  assert.equal(harness.requests[0].path, "/api/v1/experiments");
  assert.equal(harness.requests[0].method, "POST");
  assert.deepEqual(JSON.parse(harness.requests[0].body), {name: experiment.name, notes: experiment.notes});
  assert.equal(harness.run("state.captureExperimentId"), "exp-a");
  assert.equal(dialog.open, false);

  // The new experiment is selected immediately; its separate group-list read must settle before creating a group.
  await new Promise(setImmediate);
  click("group-new");
  assert.equal(dialog.open, true);
  assert.equal(harness.node("#grouping-dialog-title").textContent, "新建分组");
  assert.equal(harness.node("#experiment-fields").hidden, true);
  assert.match(harness.node("#grouping-dialog-context").textContent, /Tank A/);
  assert.equal(harness.node("#group-name").value, "");
  harness.node("#group-name").value = group.name;
  harness.node("#group-cell-id").value = `  ${group.cell_id}  `;
  harness.node("#group-notes").value = `  ${group.notes}  `;
  harness.responses.push({payload: group});
  await submit();
  assert.equal(harness.requests.at(-1).path, "/api/v1/experiments/exp-a/groups");
  assert.equal(harness.requests.at(-1).method, "POST");
  assert.deepEqual(JSON.parse(harness.requests.at(-1).body), {name: group.name, cell_id: group.cell_id, notes: group.notes});
  assert.equal(harness.run("state.captureGroupId"), "group-a");
  harness.run(`
    state.historyFilterType = "experiment"; state.historyExperimentId = "exp-a"; state.historyGroupId = "group-a";
    state.historyCursor = "cursor-before-edit";
    state.historyItems = [{capture_id:"archived-1", capture_sequence:1, sample_count:2048, grouping_metadata:{experiment_id:"exp-a", group_id:"group-a", experiment_name:"Tank A", group_name:"Run 1", cell_id:"C-42"}}];
    state.batchSelectedCaptureIds.add("archived-1"); state.selectedCaptureIds.add("overlay-1");
    renderHistory();
  `);
  const rowLabel = () => harness.node("#capture-history").children[0].children[0].children[2].textContent;

  click("experiment-edit");
  assert.equal(harness.node("#grouping-dialog-title").textContent, "编辑实验");
  assert.equal(harness.node("#experiment-name").value, experiment.name);
  assert.equal(harness.node("#experiment-notes").value, experiment.notes);
  harness.node("#experiment-name").value = "Tank revised";
  harness.responses.push({payload: {...experiment, name: "Tank revised"}});
  await submit();
  assert.equal(harness.requests.at(-1).path, "/api/v1/experiments/exp-a");
  assert.equal(harness.requests.at(-1).method, "PATCH");
  assert.equal(harness.run("state.captureGroupId"), "group-a", "editing the experiment leaves its group selected");
  assert.match(rowLabel(), /^Tank revised · Run 1/);

  click("group-edit");
  assert.equal(harness.node("#grouping-dialog-title").textContent, "编辑分组");
  assert.equal(harness.node("#group-name").value, group.name);
  assert.equal(harness.node("#group-cell-id").value, group.cell_id);
  assert.equal(harness.node("#group-notes").value, group.notes);
  harness.node("#group-name").value = "Run revised";
  let finishSave;
  harness.responses.push(new Promise((resolve) => { finishSave = resolve; }));
  const pendingSave = submit();
  const requestCount = harness.requests.length;
  assert.equal(harness.node("#grouping-save").disabled, true);
  assert.equal(harness.node("#grouping-cancel").disabled, true);
  let cancelPrevented = false;
  dialog.listeners.cancel({preventDefault() { cancelPrevented = true; }});
  assert.equal(cancelPrevented, true, "Escape cannot dismiss a pending save");
  await submit();
  assert.equal(harness.requests.length, requestCount, "double submit only writes once");
  finishSave({ok: false, payload: {detail: "storage unavailable"}});
  await pendingSave;
  assert.equal(dialog.open, true);
  assert.equal(harness.node("#group-name").value, "Run revised");
  assert.match(harness.node("#grouping-error").textContent, /storage unavailable/);
  assert.equal(harness.node("#grouping-save").disabled, false);
  harness.run('setLanguage("en")');
  assert.equal(harness.node("#grouping-dialog-title").textContent, "Edit group");
  assert.equal(harness.node("#group-name").value, "Run revised");
  harness.node("#group-cell-id").value = "";
  harness.responses.push({payload: {...group, name: "Run revised", cell_id: ""}});
  await submit();
  assert.equal(harness.requests.at(-1).path, "/api/v1/groups/group-a");
  assert.equal(harness.requests.at(-1).method, "PATCH");
  assert.equal(harness.run("captureGroupingSnapshot().group_name"), "Run revised");
  assert.equal(rowLabel(), "Tank revised · Run revised");
  assert.deepEqual(JSON.parse(harness.run(`JSON.stringify([state.historyExperimentId, state.historyGroupId,
    state.historyCursor, [...state.batchSelectedCaptureIds], [...state.selectedCaptureIds]])`)),
    ["exp-a", "group-a", "cursor-before-edit", ["archived-1"], ["overlay-1"]]);
  assert.equal(dialog.open, false);
  assert.match(html, /<dialog\b[^>]*id="grouping-dialog"[^>]*aria-labelledby="grouping-dialog-title"/);
  assert.doesNotMatch(html, /id="group-edit-target"/);
}

async function checkLateGroupSaveFence(editing, fail) {
  const harness = makeHarness();
  const groupA = {group_id: "group-a", experiment_id: "exp-a", name: "A existing", cell_id: "cell-a", notes: "A notes", archived_count: 1};
  const groupB = {group_id: "group-b", experiment_id: "exp-b", name: "B selected", cell_id: "cell-b", notes: "B notes", archived_count: 2};
  const originalGroupsA = editing ? [groupA] : [];
  harness.run(`
    state.experiments = [
      {experiment_id: "exp-a", name: "Experiment A", notes: ""},
      {experiment_id: "exp-b", name: "Experiment B", notes: ""},
    ];
    state.captureExperimentId = "exp-a";
    state.captureGroupRevision = 4;
    state.captureGroups = ${JSON.stringify(originalGroupsA)};
    state.groupsByExperiment = new Map([
      ["exp-a", ${JSON.stringify(originalGroupsA)}],
      ["exp-b", [${JSON.stringify(groupB)}]],
    ]);
    state.captureGroupId = ${JSON.stringify(editing ? "group-a" : null)};
  `);
  harness.run("bindActions()");
  harness.node(editing ? "#group-edit" : "#group-new").listeners.click();
  harness.node("#group-name").value = editing ? "A edited" : "A created";
  harness.node("#group-cell-id").value = editing ? "cell-a" : "cell-new";
  harness.node("#group-notes").value = "request A";
  let resolveSave; let rejectSave;
  const saveResponse = new Promise((resolve, reject) => { resolveSave = resolve; rejectSave = reject; });
  harness.responses.push(saveResponse);
  const pendingSave = harness.node("#grouping-form").listeners.submit({preventDefault() {}});
  assert.equal(harness.requests[0].path, editing ? "/api/v1/groups/group-a" : "/api/v1/experiments/exp-a/groups");

  harness.responses.push({ payload: { items: [groupB] } });
  await harness.run('selectCaptureExperiment("exp-b")');
  harness.node("#grouping-dialog").close();
  harness.run(`
    state.captureGroupId = "group-b";
    openGroupingEditor("group", true);
    $("#group-name").value = "B unsaved draft";
    $("#group-notes").value = "B editor notes";
    $("#toast").textContent = "B current message";
    $("#toast").hidden = false;
  `);

  if (fail) rejectSave(new Error("late A save failed"));
  else resolveSave({ payload: editing
    ? {...groupA, name: "A edited", notes: "request A"}
    : {group_id: "group-a-new", experiment_id: "exp-a", name: "A created", cell_id: "cell-new", notes: "request A", archived_count: 0} });
  await pendingSave;

  assert.equal(harness.run("state.captureExperimentId"), "exp-b");
  assert.equal(harness.run("state.captureGroupId"), "group-b");
  assert.equal(harness.run("state.groupingEditor.id"), "group-b");
  assert.equal(harness.node("#grouping-dialog").open, true);
  assert.deepEqual(JSON.parse(harness.run("JSON.stringify(state.captureGroups.map((group) => group.group_id))")), ["group-b"]);
  assert.deepEqual(JSON.parse(harness.run("JSON.stringify(state.groupsByExperiment.get('exp-b').map((group) => group.group_id))")), ["group-b"]);
  assert.deepEqual(
    JSON.parse(harness.run("JSON.stringify(state.groupsByExperiment.get('exp-a').map((group) => group.name))")),
    fail ? originalGroupsA.map((group) => group.name) : (editing ? ["A edited"] : ["A created"]),
  );
  assert.equal(harness.node("#group-name").value, "B unsaved draft");
  assert.equal(harness.node("#group-notes").value, "B editor notes");
  assert.equal(harness.node("#toast").textContent, "B current message");
  assert.equal(harness.run("captureGroupingSnapshot().group_id"), "group-b");
  assert.equal(harness.run("captureGroupingSnapshot().experiment_id"), "exp-b");
}

async function checkSameExperimentLateGroupSave(editing, fail) {
  const harness = makeHarness();
  const groupA1 = {group_id: "group-a1", experiment_id: "exp-a", name: "A1", cell_id: "cell-a1", notes: "A1 notes", archived_count: 1};
  const groupA2 = {group_id: "group-a2", experiment_id: "exp-a", name: "A2", cell_id: "cell-a2", notes: "A2 notes", archived_count: 2};
  const initialGroups = [groupA1, groupA2];
  harness.run(`
    state.experiments = [{experiment_id: "exp-a", name: "Experiment A", notes: ""}];
    state.captureExperimentId = "exp-a";
    state.captureGroupRevision = 12;
    state.captureGroups = ${JSON.stringify(initialGroups)};
    state.groupsByExperiment = new Map([["exp-a", ${JSON.stringify(initialGroups)}]]);
    state.captureGroupId = "group-a1";
  `);
  harness.run("bindActions()");
  harness.node(editing ? "#group-edit" : "#group-new").listeners.click();
  harness.node("#group-name").value = editing ? "A1 edited" : "A1 created";
  harness.node("#group-cell-id").value = "cell-a1";
  harness.node("#group-notes").value = "A1 request";
  let resolveSave; let rejectSave;
  const saveResponse = new Promise((resolve, reject) => { resolveSave = resolve; rejectSave = reject; });
  harness.responses.push(saveResponse);
  const pendingSave = harness.node("#grouping-form").listeners.submit({preventDefault() {}});
  assert.equal(harness.requests[0].path, editing ? "/api/v1/groups/group-a1" : "/api/v1/experiments/exp-a/groups");

  harness.node("#capture-group").value = "group-a2";
  harness.node("#capture-group").listeners.change();
  assert.equal(harness.run("state.captureGroupId"), "group-a2");
  assert.equal(harness.run("state.captureGroupRevision"), 12, "changing capture selection must not invalidate group-list reads");
  harness.node("#group-name").value = "current editor draft";
  harness.node("#group-notes").value = "current editor notes";
  harness.run(`$("#toast").textContent = "A2 selection message"; $("#toast").hidden = false;`);

  if (fail) rejectSave(new Error("late A1 save failed"));
  else resolveSave({ payload: editing
    ? {...groupA1, name: "A1 saved", notes: "A1 request"}
    : {group_id: "group-a1-created", experiment_id: "exp-a", name: "A1 created", cell_id: "cell-a1", notes: "A1 request", archived_count: 0} });
  await pendingSave;

  assert.equal(harness.run("state.captureExperimentId"), "exp-a");
  assert.equal(harness.run("state.captureGroupId"), "group-a2");
  assert.equal(harness.run("captureGroupingSnapshot().group_id"), "group-a2");
  assert.equal(harness.run("state.groupingEditor.id ?? null"), editing ? "group-a1" : null);
  assert.equal(harness.node("#grouping-dialog").open, true);
  assert.equal(harness.node("#group-name").value, "current editor draft");
  assert.equal(harness.node("#group-notes").value, "current editor notes");
  assert.equal(harness.node("#toast").textContent, "A2 selection message");
  const cachedNames = JSON.parse(harness.run("JSON.stringify(state.groupsByExperiment.get('exp-a').map((group) => group.name).sort())"));
  assert.deepEqual(cachedNames, fail ? ["A1", "A2"] : editing ? ["A1 saved", "A2"] : ["A1", "A1 created", "A2"]);
}

async function checkLateGroupSaveEditorSwitch(context) {
  const harness = makeHarness();
  const groupA1 = {group_id: "group-a1", experiment_id: "exp-a", name: "A1", cell_id: "cell-a1", notes: "A1 notes", archived_count: 1};
  const groupA2 = {group_id: "group-a2", experiment_id: "exp-a", name: "A2", cell_id: "cell-a2", notes: "A2 notes", archived_count: 2};
  const initialGroups = [groupA1, groupA2];
  const creating = context === "new";
  harness.run(`
    state.experiments = [{experiment_id: "exp-a", name: "Experiment A", notes: ""}];
    state.captureExperimentId = "exp-a";
    state.captureGroupRevision = 20;
    state.captureGroups = ${JSON.stringify(initialGroups)};
    state.groupsByExperiment = new Map([["exp-a", ${JSON.stringify(initialGroups)}]]);
    state.captureGroupId = ${JSON.stringify(creating ? "group-a2" : "group-a1")};
  `);
  harness.run("bindActions()");
  harness.node(creating ? "#group-new" : "#group-edit").listeners.click();
  harness.node("#group-name").value = creating ? "A1 new group" : "A1 edited";
  harness.node("#group-cell-id").value = "cell-a1";
  harness.node("#group-notes").value = "A1 request";
  let resolveSave;
  const saveResponse = new Promise((resolve) => { resolveSave = resolve; });
  harness.responses.push(saveResponse);
  const pendingSave = harness.node("#grouping-form").listeners.submit({preventDefault() {}});
  assert.equal(harness.requests[0].path, creating ? "/api/v1/experiments/exp-a/groups" : "/api/v1/groups/group-a1");

  // Programmatic close models an obsolete editor even while user dismissals are disabled.
  harness.node("#grouping-dialog").close();
  if (creating) {
    harness.node("#group-new").listeners.click();
    harness.node("#group-name").value = "next group draft";
    harness.node("#group-notes").value = "next group notes";
  } else {
    harness.node("#capture-group").value = "group-a2";
    harness.node("#capture-group").listeners.change();
    harness.node("#group-edit").listeners.click();
  }
  harness.run(`$("#toast").textContent = "current editor message"; $("#toast").hidden = false;`);
  const currentEditor = {
    editingId: harness.run("state.groupingEditor.id"),
    name: harness.node("#group-name").value,
    notes: harness.node("#group-notes").value,
  };
  resolveSave({ payload: creating
    ? {group_id: "group-a1-created", experiment_id: "exp-a", name: "A1 new group", cell_id: "cell-a1", notes: "A1 request", archived_count: 0}
    : {...groupA1, name: "A1 saved", notes: "A1 request"} });
  await pendingSave;

  assert.equal(harness.run("state.captureGroupId"), "group-a2");
  assert.equal(harness.run("captureGroupingSnapshot().group_id"), "group-a2");
  assert.deepEqual({
    editingId: harness.run("state.groupingEditor.id"),
    name: harness.node("#group-name").value,
    notes: harness.node("#group-notes").value,
  }, currentEditor);
  assert.equal(harness.node("#toast").textContent, "current editor message");
}

async function checkExperimentHistoryFilters() {
  const modes = html.match(/<select id="history-filter-type">(.*?)<\/select>/s)[1];
  assert.deepEqual([...modes.matchAll(/<option value="([^"]+)"/g)].map((match) => match[1]),
    ["all", "experiment"], "History exposes only all captures and experiment modes");
  const harness = makeHarness();
  harness.run(`
    state.experiments = [{experiment_id:"A", name:"Experiment A"}, {experiment_id:"B", name:"Experiment B"}, {experiment_id:"C", name:"Empty experiment"}];
    state.groupsByExperiment = new Map([
      ["A", [{group_id:"a1", experiment_id:"A", name:"Baseline"}, {group_id:"a2", experiment_id:"A", name:"Comparison"}]],
      ["B", [{group_id:"b1", experiment_id:"B", name:"Other experiment group"}]], ["C", []],
    ]);
    state.captureExperimentId = "B";
    state.captureGroups = state.groupsByExperiment.get("B");
    state.captureGroupId = "b1";
    bindActions(); renderHistoryFilterOptions();
  `);
  const filterMode = harness.node("#history-filter-type");
  const experiment = harness.node("#history-experiment");
  const groupPanel = harness.node("#history-group-filters");
  const choices = harness.node("#history-group-choices");
  const query = () => new URL(harness.requests.at(-1).path, "http://localhost").searchParams;
  const records = (ids, cursor = null) => ({payload: {items: ids.map((capture_id) => ({capture_id, capture_sequence:1, sample_count:2})), next_cursor:cursor}});
  const recordIds = () => JSON.parse(harness.run("JSON.stringify(state.historyItems.map((item) => item.capture_id))"));
  const names = () => choices.children.map((button) => button.textContent);
  const pressed = () => choices.children.filter((button) => button["aria-pressed"] === "true").map((button) => button.textContent);
  const chooseExperiment = async (id) => { experiment.value = id; await experiment.listeners.change(); };
  const clickGroup = async (label) => { await choices.children.find((button) => button.textContent === label).listeners.click(); };

  assert.equal(harness.node("#history-experiment-field").hidden, true);
  assert.equal(groupPanel.hidden, true);
  harness.responses.push(records(["legacy-ungrouped", "a1-record", "b1-record"]));
  await harness.node("#history-refresh").listeners.click();
  assert.deepEqual(recordIds(), ["legacy-ungrouped", "a1-record", "b1-record"]);
  assert.equal(query().has("experiment_id"), false);
  assert.equal(query().has("ungrouped"), false);

  filterMode.value = "experiment";
  await filterMode.listeners.change();
  assert.equal(harness.node("#history-experiment-field").hidden, false);
  assert.equal(groupPanel.hidden, true);
  assert.equal(harness.requests.length, 1, "waiting for an experiment does not fetch all captures");
  assert.deepEqual(recordIds(), []);

  harness.responses.push(records(["a1-record", "a2-record"]));
  await chooseExperiment("A");
  assert.equal(groupPanel.hidden, false);
  assert.deepEqual(names(), ["全部分组", "Baseline", "Comparison"]);
  assert.deepEqual(pressed(), ["全部分组"]);
  assert.equal(query().get("experiment_id"), "A");
  assert.equal(query().has("group_id"), false);
  assert.deepEqual(recordIds(), ["a1-record", "a2-record"]);
  assert.equal(harness.run("captureGroupingSnapshot().group_id"), "b1", "history filtering does not change acquisition grouping");

  harness.responses.push(records(["a2-record"], "later-a2"));
  await clickGroup("Comparison");
  assert.deepEqual(pressed(), ["Comparison"]);
  assert.deepEqual(Object.fromEntries(query()), {limit:"20", experiment_id:"A", group_id:"a2"});
  assert.deepEqual(recordIds(), ["a2-record"]);
  harness.run('state.batchSelectedCaptureIds.add("a2-record"); state.selectedCaptureIds.add("overlay-kept");');
  let finishOldPage;
  harness.responses.push(new Promise((resolve) => { finishOldPage = resolve; }), records(["b1-record"]));
  const oldPage = harness.node("#history-more").listeners.click();
  assert.deepEqual(Object.fromEntries(query()), {limit:"20", cursor:"later-a2", experiment_id:"A", group_id:"a2"});
  await chooseExperiment("B");
  assert.deepEqual(Object.fromEntries(query()), {limit:"20", experiment_id:"B"});
  assert.deepEqual(names(), ["全部分组", "Other experiment group"]);
  assert.deepEqual(pressed(), ["全部分组"]);
  finishOldPage(records(["stale-record"], "old-cursor"));
  await oldPage;
  assert.deepEqual(recordIds(), ["b1-record"]);
  assert.equal(harness.run("state.historyCursor"), null);
  assert.equal(harness.run("state.batchSelectedCaptureIds.size"), 0);
  assert.equal(harness.run('state.selectedCaptureIds.has("overlay-kept")'), true);
  harness.responses.push(records(["b1-record"]), records(["b1-record"]));
  await clickGroup("Other experiment group");
  assert.equal(query().get("group_id"), "b1");
  await clickGroup("全部分组");
  assert.equal(query().has("group_id"), false);
  harness.run('setLanguage("en")');
  assert.deepEqual(pressed(), ["All groups"]);

  harness.responses.push(records([]));
  await chooseExperiment("C");
  assert.deepEqual(names(), []);
  assert.match(harness.node("#history-group-hint").textContent, /no groups/);

  filterMode.value = "all";
  harness.responses.push(records(["legacy-ungrouped", "a1-record", "b1-record"]));
  await filterMode.listeners.change();
  assert.equal(groupPanel.hidden, true);
  assert.deepEqual(Object.fromEntries(query()), {limit:"20"});
  assert.deepEqual(recordIds(), ["legacy-ungrouped", "a1-record", "b1-record"]);
}

async function checkIncompleteHistoryTarget(automatic) {
  const harness = makeHarness();
  harness.run(`
    state.historyFilterType = "experiment";
    state.historyExperimentId = "";
    state.historyCursor = "old-cursor";
    state.historyItems = [{capture_id: "old-history", capture_sequence: 1, sample_count: 2, grouping_metadata: {group_id: null}}];
    state.batchSelectedCaptureIds = new Set(["old-history"]);
    state.active = ${automatic ? '{mode: "PERIODIC", session_id: "session-finished", save_policy: "SAVE_ALL", grouping_metadata: {experiment_id: null}}' : 'null'};
  `);
  harness.node("#history-more").hidden = false;
  if (automatic) {
    harness.responses.push({ payload: {state: "COMPLETED", acquired_count: 1} });
    await harness.run("pollSession()");
  } else {
    harness.run("bindActions()");
    await harness.node("#history-refresh").listeners.click();
  }
  assert.deepEqual(
    harness.requests.filter((request) => request.path.startsWith("/api/v1/captures?")),
    [],
    `${automatic ? "automatic completion" : "manual refresh"} must not load captures without an experiment`,
  );
  assert.deepEqual(JSON.parse(harness.run("JSON.stringify([state.historyItems.length, state.historyCursor, [...state.batchSelectedCaptureIds]])")), [0, null, []]);
  assert.equal(harness.node("#history-more").hidden, true);
}

async function main() {
  await checkHistoryUsesFreshGroupingMetadata();
  await checkExperimentHistoryFilters();
  await checkGroupingDialog();
  [
    "waveform-workbench", "window-start", "window-count", "waveform-mode",
    "waveform-previous", "waveform-next", "waveform-apply-window",
    "overlay-count", "waveform-legend", "resume-latest", "waveform-show-all",
    "waveform-clear-overlays", "storage-paths",
    "parameter-bank-jump",
  ].forEach((id) => assert.match(html, new RegExp(`id=["']${id}["']`)));
  assert.ok(html.indexOf("acquisition-card") < html.indexOf("waveform-workbench"));
  assert.ok(html.indexOf("waveform-workbench") < html.indexOf("capture-history"));
  assert.ok(html.indexOf("capture-history") < html.indexOf('id="parameter-bank"'));
  const cellMetadataLanguage = makeHarness();
  assert.equal(cellMetadataLanguage.run("I18N.zh['group.cellId']"), "电芯编号（可选）");
  assert.equal(cellMetadataLanguage.run("I18N.zh['group.cell']"), "电芯编号 {cell}");
  assert.equal(cellMetadataLanguage.run("I18N.en['group.cell']"), "Cell ID {cell}");
  assert.equal(cellMetadataLanguage.run("I18N.zh['group.invalidCell']"), "电芯编号不得超过 120 个字符。");
  assert.match(html, /data-i18n="group\.cellId">电芯编号（可选）/);

  const waveform = makeHarness();
  assert.deepEqual(
    Array.from(waveform.run("decodeSamples(Uint8Array.from([52, 18, 205, 171]), 2)")),
    [0x1234, 0xabcd],
  );
  assert.throws(() => waveform.run("decodeSamples(Uint8Array.from([1]), null)"), /even/);
  assert.throws(
    () => waveform.run("decodeSamples(Uint8Array.from([1, 0, 2, 0]), 3)"),
    /sample count/,
  );
  assert.deepEqual(
    Array.from(waveform.run("normalizeFrame(Uint16Array.from([10, 20, 30]))")),
    [0, 0.5, 1],
  );
  assert.deepEqual(
    Array.from(waveform.run("normalizeFrame(Uint16Array.from([7, 7]))")),
    [0, 0],
  );
  assert.deepEqual(
    JSON.parse(waveform.run("JSON.stringify(validatedWindow(4, 3, 10))")),
    { start: 4, count: 3 },
  );
  assert.throws(() => waveform.run("validatedWindow(9, 2, 10)"), /window/);
  assert.deepEqual(
    JSON.parse(waveform.run("JSON.stringify(shiftedWindow(6, 4, 10, 1))")),
    { start: 6, count: 4 },
  );
  assert.deepEqual(
    JSON.parse(waveform.run("JSON.stringify(shiftedWindow(6, 4, 10, -1))")),
    { start: 2, count: 4 },
  );
  assert.deepEqual(
    Array.from(waveform.run("basisDifferences({sample_interval_ticks: 120, pretrigger_count: 64, sample_count: 2048}, {sample_interval_ticks: 60, pretrigger_count: 64, sample_count: 1024})")),
    ["sample_interval_ticks", "sample_count"],
  );
  waveform.node("#waveform").width = 720;
  waveform.node("#waveform").height = 280;
  waveform.run("drawWaveforms(document.querySelector('#waveform'), [{samples: Uint16Array.from([42]), color: '#fff', visible: true}], {start: 0, count: 1}, 'raw')");
  const marker = waveform.canvasOps.find((operation) => operation[0] === "arc");
  assert.ok(marker, "one sample must render as a point");
  assert.equal(marker[1], 360);
  const firstAxisLabel = waveform.canvasOps.find((operation) => operation[0] === "fillText");
  assert.equal(firstAxisLabel.at(-2), "#b8c6c1");
  assert.match(firstAxisLabel.at(-1), /px/);

  const bounded = makeHarness();
  bounded.run("resetWaveformGroup('capture-0')");
  const primaryLoad = bounded.run("reserveWaveform('capture-0')");
  assert.equal(
    bounded.run("commitWaveformLoad")(primaryLoad, {
      samples: Uint16Array.from([1, 2]), color: "#fff", visible: true,
    }),
    true,
  );
  bounded.run("resetWaveformGroup('capture-0')");
  bounded.run("reserveWaveform('capture-0')");
  for (let index = 1; index < 20; index += 1) bounded.run(`reserveWaveform('capture-${index}')`);
  bounded.run("state.waveforms.set('capture-1', {samples: Uint16Array.from([1]), visible: false}); state.waveformLoads.delete('capture-1')");
  assert.equal(bounded.run("state.selectedCaptureIds.size"), 20);
  assert.throws(() => bounded.run("reserveWaveform('capture-20')"), /20/);
  bounded.run("removeWaveform('capture-1')");
  assert.equal(bounded.run("state.selectedCaptureIds.size"), 19);
  bounded.run("reserveWaveform('capture-20')");
  assert.equal(bounded.run("state.selectedCaptureIds.size"), 20);

  const ownership = makeHarness();
  ownership.run("resetWaveformGroup('A')");
  const loadA = ownership.run("reserveWaveform('A')");
  ownership.run("resetWaveformGroup('B')");
  const loadB = ownership.run("reserveWaveform('B')");
  assert.equal(
    ownership.run("commitWaveformLoad")(loadA, {
      samples: Uint16Array.from([10]), color: "#aaa", visible: true,
    }),
    false,
  );
  assert.equal(ownership.run("rejectWaveformLoad")(loadA), false);
  assert.deepEqual(Array.from(ownership.run("state.selectedCaptureIds")), ["B"]);
  assert.equal(ownership.run("state.waveformLoads.get('B').token"), loadB.token);
  assert.equal(
    ownership.run("commitWaveformLoad")(loadB, {
      samples: Uint16Array.from([20]), color: "#bbb", visible: true,
    }),
    true,
  );
  assert.equal(ownership.run("state.waveforms.has('B')"), true);

  const historyView = makeHarness();
  const savedSummary = {
    capture_id: "history-a", capture_sequence: 7, sample_count: 2,
    sample_interval_ticks: 120, pretrigger_count: 64, storage: "ARCHIVE",
  };
  historyView.responses.push({ bytes: [10, 0, 20, 0] });
  await historyView.run("viewHistoricalCapture")(savedSummary);
  assert.equal(historyView.run("state.followLatest"), false);
  assert.equal(historyView.run("state.primaryCaptureId"), "history-a");
  assert.equal(historyView.requests.at(-1).path, "/api/v1/captures/history-a/samples");

  const staleMetadata = makeHarness();
  let resolveMetadataA;
  staleMetadata.responses.push(
    new Promise((resolve) => { resolveMetadataA = resolve; }),
    { bytes: [30, 0, 40, 0] },
  );
  const loadingA = staleMetadata.run("refreshLatestWaveform")({ last_capture_id: "live-a" });
  await Promise.resolve();
  await staleMetadata.run("viewHistoricalCapture")({
    capture_id: "history-b", capture_sequence: 2, sample_count: 2,
    sample_interval_ticks: 120, pretrigger_count: 64,
  });
  resolveMetadataA({ payload: {
    capture_id: "live-a", sample_count: 2, sample_interval_ticks: 120,
    pretrigger_count: 64, storage: "TRANSIENT",
  } });
  await loadingA;
  assert.deepEqual(Array.from(staleMetadata.run("state.selectedCaptureIds")), ["history-b"]);
  assert.equal(staleMetadata.requests.some((request) => request.path === "/api/v1/captures/live-a/samples"), false);

  const pendingPrimaryBasis = makeHarness();
  let resolvePrimaryMetadata;
  pendingPrimaryBasis.responses.push(
    new Promise((resolve) => { resolvePrimaryMetadata = resolve; }),
    { bytes: [70, 0, 80, 0] },
    { bytes: [90, 0, 100, 0] },
  );
  const loadingPrimary = pendingPrimaryBasis.run("refreshLatestWaveform")({ last_capture_id: "live-primary" });
  await Promise.resolve();
  await pendingPrimaryBasis.run("toggleHistoryCapture")({
    capture_id: "history-incompatible", capture_sequence: 4, sample_count: 2,
    sample_interval_ticks: 240, pretrigger_count: 64,
  }, true);
  assert.equal(
    pendingPrimaryBasis.requests.some((request) => request.path === "/api/v1/captures/history-incompatible/samples"),
    false,
    "history overlay must wait until the primary sampling basis is known",
  );
  assert.match(pendingPrimaryBasis.node("#toast").textContent, /主波形/);
  resolvePrimaryMetadata({ payload: {
    capture_id: "live-primary", sample_count: 2, sample_interval_ticks: 120,
    pretrigger_count: 64, storage: "TRANSIENT",
  } });
  await loadingPrimary;
  assert.deepEqual(Array.from(pendingPrimaryBasis.run("state.selectedCaptureIds")), ["live-primary"]);

  const staleMetadataFailure = makeHarness();
  staleMetadataFailure.node("#toast").hidden = true;
  let rejectMetadataA;
  staleMetadataFailure.responses.push(
    new Promise((resolve) => { rejectMetadataA = resolve; }),
    { bytes: [50, 0, 60, 0] },
  );
  const failingA = staleMetadataFailure.run("refreshLatestWaveform")({ last_capture_id: "live-fail" });
  await Promise.resolve();
  await staleMetadataFailure.run("viewHistoricalCapture")({
    capture_id: "history-c", capture_sequence: 3, sample_count: 2,
    sample_interval_ticks: 120, pretrigger_count: 64,
  });
  rejectMetadataA({ ok: false, status: 500, payload: { detail: "old metadata failed" } });
  await failingA;
  assert.equal(staleMetadataFailure.node("#toast").hidden, true);

  const preservedWindow = makeHarness();
  preservedWindow.run("state.windowStart = 128; state.windowCount = 64; resetWaveformGroup('window-a');");
  preservedWindow.responses.push({ bytes: Array.from({ length: 512 }, (_value, index) => index % 256) });
  await preservedWindow.run("loadWaveform")({
    capture_id: "window-a", sample_count: 256, sample_interval_ticks: 120,
    pretrigger_count: 64, storage: "ARCHIVE",
  });
  assert.deepEqual(Array.from(preservedWindow.run("[state.windowStart, state.windowCount]")), [128, 64]);
  preservedWindow.run("showAllWaveform()") ;
  assert.deepEqual(Array.from(preservedWindow.run("[state.windowStart, state.windowCount]")), [0, 256]);

  const clearOverlay = makeHarness();
  clearOverlay.run(`
    state.primaryCaptureId = "primary";
    ["primary", "extra"].forEach((id) => { state.selectedCaptureIds.add(id); state.waveforms.set(id, {metadata: {capture_id: id}, samples: Uint16Array.from([1, 2]), color: "#fff", visible: true}); });
    clearWaveformOverlays();
  `);
  assert.deepEqual(Array.from(clearOverlay.run("state.selectedCaptureIds")), ["primary"]);

  const invalidWindow = makeHarness();
  invalidWindow.run(`
    state.language = "zh"; state.primaryCaptureId = "invalid";
    state.selectedCaptureIds.add("invalid");
    state.waveforms.set("invalid", {metadata: {capture_id: "invalid"}, samples: Uint16Array.from([1, 2]), color: "#fff", visible: true});
  `);
  invalidWindow.node("#window-start").value = "2"; invalidWindow.node("#window-count").value = "1";
  assert.throws(() => invalidWindow.run("applyWaveformWindow()"), /波形窗口/);

  const incompatible = makeHarness();
  incompatible.node("#toast").hidden = true;
  incompatible.run(`
    state.followLatest = false;
    state.primaryCaptureId = "basis-a";
    state.selectedCaptureIds.add("basis-a");
    state.waveforms.set("basis-a", {metadata: {capture_id: "basis-a", sample_count: 2048, sample_interval_ticks: 120, pretrigger_count: 64}, samples: new Uint16Array(2048), color: "#fff", visible: true});
  `);
  await incompatible.run("toggleHistoryCapture")({
    capture_id: "basis-b", sample_count: 2048, sample_interval_ticks: 60, pretrigger_count: 64,
  }, true);
  assert.equal(incompatible.requests.length, 0, "incompatible history is rejected before sample download");
  assert.match(incompatible.node("#toast").textContent, /sample_interval_ticks/);

  const paused = makeHarness();
  paused.run("state.followLatest = false; state.latestCaptureId = 'old';");
  await paused.run("refreshLatestWaveform")({ last_capture_id: "new-live" });
  assert.equal(paused.run("state.latestCaptureId"), "new-live");
  assert.equal(paused.requests.length, 0);

  const resumed = makeHarness();
  resumed.run("state.followLatest = false; state.latestCaptureId = 'latest-b'; resetWaveformGroup('history-b');");
  resumed.responses.push(
    { payload: { capture_id: "latest-b", sample_count: 2, sample_interval_ticks: 60, pretrigger_count: 32, storage: "TRANSIENT" } },
    { bytes: [30, 0, 40, 0] },
  );
  await resumed.run("resumeLatestWaveform()") ;
  assert.equal(resumed.run("state.followLatest"), true);
  assert.deepEqual(Array.from(resumed.run("state.selectedCaptureIds")), ["latest-b"]);
  assert.deepEqual(resumed.requests.map((request) => request.path), [
    "/api/v1/captures/latest-b", "/api/v1/captures/latest-b/samples",
  ]);

  const storage = makeHarness();
  storage.responses.push({ payload: {
    backend: "sqlite", runtime_database_path: "/var/lib/usac/database/acquisition.sqlite3",
    host_database_path: "D:/Desktop/TUSS4470_data/core/acquisition.sqlite3", path_mapping: "bind_mount",
  } });
  await storage.run("loadStorage()") ;
  assert.equal(storage.node("#storage-host-path").textContent, "D:/Desktop/TUSS4470_data/core/acquisition.sqlite3");
  assert.equal(storage.node("#storage-runtime-path").textContent, "/var/lib/usac/database/acquisition.sqlite3");

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
    { payload: { capture_id: "capture-1", sample_count: 2, sample_interval_ticks: 120, pretrigger_count: 64, storage: "ROLLING_LATEST" } },
    { bytes: [1, 0, 2, 0] },
  );
  await live.run("pollSession()");
  live.responses.push(
    { payload: { state: "RUNNING", acquired_count: 2, last_capture_id: "capture-2" } },
    { payload: { capture_id: "capture-2", sample_count: 2, sample_interval_ticks: 60, pretrigger_count: 64, storage: "ROLLING_LATEST" } },
    { bytes: [3, 0, 4, 0] },
  );
  await live.run("pollSession()");
  assert.deepEqual(
    live.requests.filter((request) => request.path.endsWith("/samples")).map((request) => request.path),
    ["/api/v1/captures/capture-1/samples", "/api/v1/captures/capture-2/samples"],
  );
  assert.deepEqual(
    live.requests.filter((request) => !request.path.endsWith("/samples")).map((request) => request.path),
    ["/api/v1/sessions/session-2", "/api/v1/captures/capture-1", "/api/v1/sessions/session-2", "/api/v1/captures/capture-2"],
  );
  assert.equal(live.run("state.waveforms.get('capture-2').metadata.sample_interval_ticks"), 60);
  assert.equal(live.run('Object.hasOwn(state, "waveformSamples")'), false);

  const retry = makeHarness();
  retry.node("#toast").hidden = true;
  retry.run('state.active = {mode: "PERIODIC", session_id: "session-3", schedule_id: "schedule-3"};');
  retry.responses.push(
    { payload: { state: "RUNNING", acquired_count: 1, last_capture_id: "capture-3" } },
    { ok: false, status: 404, payload: { detail: "transient frame was replaced" } },
  );
  const timersBeforeFailure = retry.timers.length;
  await retry.run("pollSession()");
  assert.ok(retry.timers.length > timersBeforeFailure);
  assert.equal(retry.run("state.active.session_id"), "session-3");
  assert.equal(retry.node("#toast").hidden, true, "a replaced transient frame is skipped without an error toast");
  assert.equal(retry.run("state.selectedCaptureIds.size"), 0);

  const saveLastTerminal = makeHarness();
  saveLastTerminal.run(`
    state.active = {mode: "PERIODIC", session_id: "session-save-last", schedule_id: "schedule-save-last", save_policy: "SAVE_LAST"};
    resetWaveformGroup("capture-last");
    state.latestCaptureId = "capture-last";
    state.waveforms.set("capture-last", {metadata: {capture_id: "capture-last", storage: "ROLLING_LATEST"}, samples: Uint16Array.from([1, 2]), color: "#fff", visible: true});
  `);
  saveLastTerminal.responses.push(
    { payload: { state: "COMPLETED", acquired_count: 1, last_capture_id: "capture-last" } },
    { payload: { capture_id: "capture-last", sample_count: 2, sample_interval_ticks: 120, pretrigger_count: 64, storage: "ARCHIVE" } },
    { payload: { items: [], next_cursor: null } },
  );
  await saveLastTerminal.run("pollSession()") ;
  assert.equal(saveLastTerminal.run("state.waveforms.get('capture-last').metadata.storage"), "ARCHIVE");
  assert.equal(saveLastTerminal.requests.filter((request) => request.path.endsWith("/samples")).length, 0);

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

  for (const mode of ["SINGLE", "PERIODIC", "SWEEP"]) {
    const frozen = makeHarness();
    Object.entries({
      "#capture-mode": mode, "#save-policy": "SAVE_NONE",
      "#trigger-source": "SOFTWARE", "#sync-timeout": "0", "#sweep-values": "[1]",
    }).forEach(([selector, value]) => { frozen.node(selector).value = value; });
    frozen.run(`
      state.connected = true;
      state.config = {state: "APPLIED", actual: {profile_sha256: "abc", device_config_crc32: 123}};
      state.captureExperimentId = "experiment-at-click";
      state.captureGroupId = "group-at-click";
      state.experiments = [{experiment_id: "experiment-at-click", name: "Tank", notes: "baseline"}];
      state.captureGroups = [{group_id: "group-at-click", experiment_id: "experiment-at-click", name: "Run A", cell_id: "cell-1", notes: "first", archived_count: 2}];
      refreshLatestWaveform = async () => {};
      refreshGroupCatalog = async () => [];
      loadHistory = async () => {};
      pollSession = async () => {};
    `);
    let finishRequest;
    frozen.responses.push(new Promise((resolve) => { finishRequest = resolve; }));
    const started = frozen.run("startCapture()");
    await Promise.resolve();
    const request = frozen.requests.find((item) => item.method === "POST");
    assert.ok(request, `${mode} sends a start request`);
    assert.equal(JSON.parse(request.body).group_id, "group-at-click", `${mode} freezes group at click, including SAVE_NONE`);
    frozen.run('state.captureGroupId = "group-after-click";');
    finishRequest({ payload: mode === "SINGLE" ? {capture_id: "one"} : {session_id: "session-1", schedule_id: "schedule-1"} });
    await started;
  }

  const lateGroupSuccess = makeHarness();
  assert.equal(lateGroupSuccess.run("typeof loadCaptureGroups"), "function", "group-list loading is a real controller function");
  let finishGroupA;
  lateGroupSuccess.responses.push(
    new Promise((resolve) => { finishGroupA = resolve; }),
    { payload: { items: [{group_id: "group-b", experiment_id: "B", name: "B group", cell_id: null, notes: "", archived_count: 4}] } },
  );
  const groupsA = lateGroupSuccess.run("selectCaptureExperiment('A')");
  await Promise.resolve();
  const groupsB = lateGroupSuccess.run("selectCaptureExperiment('B')");
  await Promise.resolve();
  await groupsB;
  finishGroupA({ payload: { items: [{group_id: "group-a", experiment_id: "A", name: "stale group", cell_id: null, notes: "", archived_count: 9}] } });
  await groupsA;
  assert.deepEqual(JSON.parse(lateGroupSuccess.run("JSON.stringify(state.captureGroups.map((item) => item.group_id))")), ["group-b"]);
  assert.equal(lateGroupSuccess.run("state.captureGroupId"), null, "changing experiments clears the selected group immediately");

  const lateGroupFailure = makeHarness();
  lateGroupFailure.node("#toast").hidden = true;
  let failGroupA;
  lateGroupFailure.responses.push(
    new Promise((resolve) => { failGroupA = resolve; }),
    { payload: { items: [{group_id: "group-b", experiment_id: "B", name: "B group", cell_id: null, notes: "", archived_count: 0}] } },
  );
  const failedGroupsA = lateGroupFailure.run("selectCaptureExperiment('A')");
  await Promise.resolve();
  const loadedGroupsB = lateGroupFailure.run("selectCaptureExperiment('B')");
  await Promise.resolve();
  await loadedGroupsB;
  failGroupA({ ok: false, status: 500, payload: { detail: "stale group request" } });
  await failedGroupsA;
  assert.equal(lateGroupFailure.node("#toast").hidden, true, "a stale group failure cannot replace current state");
  assert.equal(lateGroupFailure.run("state.captureGroups[0].group_id"), "group-b");

  await checkIncompleteHistoryTarget(false);
  await checkIncompleteHistoryTarget(true);

  for (const editing of [false, true]) {
    for (const fail of [false, true]) await checkSameExperimentLateGroupSave(editing, fail);
  }
  await checkLateGroupSaveEditorSwitch("new");
  await checkLateGroupSaveEditorSwitch("edit");

  await checkLateGroupSaveFence(false, false);
  await checkLateGroupSaveFence(false, true);
  await checkLateGroupSaveFence(true, false);
  await checkLateGroupSaveFence(true, true);

  const staleHistoryFailure = makeHarness();
  staleHistoryFailure.node("#toast").hidden = true;
  let failOldPage;
  staleHistoryFailure.responses.push(
    new Promise((resolve) => { failOldPage = resolve; }),
    { payload: { items: [], next_cursor: null } },
  );
  const oldFailingPage = staleHistoryFailure.run("loadHistory(false)");
  await Promise.resolve();
  await staleHistoryFailure.run("setHistoryFilter('experiment', 'current-experiment')");
  failOldPage({ ok: false, status: 500, payload: { detail: "stale page failed" } });
  await oldFailingPage;
  assert.equal(staleHistoryFailure.node("#toast").hidden, true, "a late history failure is fenced by filter revision");

  const batchIndependent = makeHarness();
  assert.equal(batchIndependent.run("typeof toggleBatchCapture"), "function", "batch selection is separate from waveform selection");
  batchIndependent.run(`
    state.selectedCaptureIds.add("overlay-id");
    state.batchSelectedCaptureIds = new Set(["already-selected"]);
    toggleBatchCapture("archive-id", true);
  `);
  assert.deepEqual(JSON.parse(batchIndependent.run("JSON.stringify([[...state.selectedCaptureIds], [...state.batchSelectedCaptureIds]])")), [["overlay-id"], ["already-selected", "archive-id"]]);

  const failedAssignment = makeHarness();
  assert.equal(failedAssignment.run("typeof assignSelectedCaptures"), "function", "assignment uses the real controller function");
  failedAssignment.node("#batch-assignment-target").value = "group-target";
  failedAssignment.run('state.batchSelectedCaptureIds = new Set(["archive-a"]);');
  failedAssignment.responses.push({ ok: false, status: 422, payload: { detail: "invalid group" } });
  await failedAssignment.run("assignSelectedCaptures()").catch(() => {});
  assert.deepEqual(JSON.parse(failedAssignment.run("JSON.stringify([...state.batchSelectedCaptureIds])")), ["archive-a"]);
  assert.equal(JSON.parse(failedAssignment.requests.at(-1).body).group_id, "group-target");

  const exportLink = makeHarness();
  assert.equal(exportLink.run("typeof renderGroupExport"), "function", "group export has a controller renderer");
  exportLink.run('state.captureGroupId = null; renderGroupExport();');
  assert.equal(exportLink.node("#group-export")["aria-disabled"], "true");
  exportLink.run(`
    state.captureGroupId = "group-zip";
    state.captureGroups = [{group_id: "group-zip", experiment_id: "exp", name: "Target group", cell_id: "cell-3", notes: "", archived_count: 12}];
    renderGroupExport();
  `);
  assert.equal(exportLink.node("#group-export").href, "/api/v1/groups/group-zip/export.zip");
  assert.match(exportLink.node("#group-export-label").textContent, /12/);

  const language = makeHarness();
  const prefixExpression = "key.startsWith('group.') || key.startsWith('history.filter.') || key.startsWith('batch.')";
  const zhKeys = JSON.parse(language.run(`JSON.stringify(Object.keys(I18N.zh).filter((key) => ${prefixExpression}).sort())`));
  const enKeys = JSON.parse(language.run(`JSON.stringify(Object.keys(I18N.en).filter((key) => ${prefixExpression}).sort())`));
  assert.ok(zhKeys.length > 0, "grouping controls have translated labels and status messages");
  assert.deepEqual(zhKeys, enKeys, "all added Chinese keys have English counterparts");
  const staticKeys = [
    ...language.staticTextNodes.map((node) => node.dataset.i18n),
    ...language.staticAriaNodes.map((node) => node.dataset.i18nAriaLabel),
  ];
  const unresolvedStaticKeys = JSON.parse(language.run(`JSON.stringify(${JSON.stringify(staticKeys)}.filter((key) => {
    const zh = I18N.zh[key]; const en = I18N.en[key];
    return typeof zh !== "string" || !zh.trim() || zh === key || typeof en !== "string" || !en.trim() || en === key;
  }))`));
  assert.deepEqual(unresolvedStaticKeys, [], "every static HTML text and ARIA key has real Chinese and English translations");
  const staticTextFor = (key) => language.staticTextNodes.find((node) => node.dataset.i18n === key);
  const staticAriaFor = (key) => language.staticAriaNodes.find((node) => node.dataset.i18nAriaLabel === key);
  language.run("setLanguage('zh')");
  for (const node of language.staticTextNodes) {
    assert.equal(node.textContent, language.run(`I18N.zh[${JSON.stringify(node.dataset.i18n)}]`));
  }
  for (const node of language.staticAriaNodes) {
    assert.equal(node.attributes["aria-label"], language.run(`I18N.zh[${JSON.stringify(node.dataset.i18nAriaLabel)}]`));
  }
  assert.equal(staticTextFor("group.manage").textContent, "管理实验与分组");
  assert.equal(staticTextFor("history.filter.mode").textContent, "筛选方式");
  language.run("setLanguage('en')");
  for (const node of language.staticTextNodes) {
    assert.equal(node.textContent, language.run(`I18N.en[${JSON.stringify(node.dataset.i18n)}]`));
  }
  for (const node of language.staticAriaNodes) {
    assert.equal(node.attributes["aria-label"], language.run(`I18N.en[${JSON.stringify(node.dataset.i18nAriaLabel)}]`));
  }
  assert.equal(staticTextFor("group.manage").textContent, "Manage experiments and groups");
  assert.equal(staticTextFor("history.filter.mode").textContent, "Filter by");
  assert.equal(staticAriaFor("language.aria").attributes["aria-label"], "Switch to Chinese");
  language.run(`
    state.captureExperimentId = "exp-a"; state.captureGroupId = "group-a";
    state.historyFilterType = "experiment"; state.historyExperimentId = "exp-a"; state.historyGroupId = "group-a";
    $("#experiment-name").value = "  unsaved draft  ";
    $("#group-notes").value = "keep me";
    setLanguage("en");
  `);
  assert.equal(language.node("#capture-experiment").value, "exp-a");
  assert.equal(language.node("#capture-group").value, "group-a");
  assert.equal(language.node("#history-experiment").value, "exp-a");
  assert.equal(language.node("#experiment-name").value, "  unsaved draft  ");
  assert.equal(language.node("#group-notes").value, "keep me");

  [
    "capture-experiment", "capture-group", "capture-binding-next", "capture-binding-active",
    "grouping-dialog", "experiment-name", "group-name", "group-cell-id",
    "history-filter-type", "history-experiment", "history-group-choices", "batch-assignment-target",
    "batch-assignment-apply", "group-export", "batch-selection-count",
  ].forEach((id) => assert.match(html, new RegExp(`id=["']${id}["']`)));
}

main().then(() => {
  process.stdout.write("Web task lifecycle: PASS\n");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
