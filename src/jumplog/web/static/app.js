"use strict";

const FIELDS = [
  { key: "paxe",       cls: "" },
  { key: "fl",         cls: "" },
  { key: "to",         cls: "" },
  { key: "ldg",        cls: "" },
  { key: "time_min",   cls: "" },
  { key: "cyc",        cls: "" },
  { key: "temp",       cls: "" },
  { key: "fuel_used",  cls: "" },
  { key: "refuel",     cls: "" },
  { key: "remarks",    cls: "remarks" },
];

const form        = document.getElementById("meta-form");
const statusEl    = document.getElementById("status");
const shellStatus = document.getElementById("shellbar-status");
const fetchBtn    = document.getElementById("fetch-btn");
const addRowBtn   = document.getElementById("add-row-btn");
const renderBtn   = document.getElementById("render-btn");
const tablePanel  = document.getElementById("table-panel");
const tbody       = document.querySelector(".lift-table tbody");

document.getElementById("date").value = new Date().toISOString().slice(0, 10);

// ---------------------------------------------------------------------------
// Status / form helpers
// ---------------------------------------------------------------------------

function setStatus(text, kind = "") {
  statusEl.textContent = text || "";
  statusEl.className = "status-bar" + (kind ? " " + kind : "");
  if (shellStatus) shellStatus.textContent = text ? text.split(/[.,]/)[0] : "Ready";
}

function formValues() {
  const fd = new FormData(form);
  const out = {};
  for (const [k, v] of fd.entries()) out[k] = (v || "").trim();
  return out;
}

// ---------------------------------------------------------------------------
// Row construction + manipulation
// ---------------------------------------------------------------------------

function makeCell(value, key, extraCls) {
  const td = document.createElement("td");
  td.className = "fd-table__cell";
  const inp = document.createElement("input");
  inp.type = "text";
  inp.dataset.key = key;
  inp.className = "cell" + (extraCls ? " " + extraCls : "");
  inp.value = value ?? "";
  inp.addEventListener("input", validate);
  td.appendChild(inp);
  return td;
}

function iconBtn(icon, label, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "row-tool";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.innerHTML = `<i class="sap-icon--${icon}" aria-hidden="true"></i>`;
  b.addEventListener("click", onClick);
  return b;
}

function buildRow(row = {}) {
  const tr = document.createElement("tr");
  tr.className = "fd-table__row";

  const numTd = document.createElement("td");
  numTd.className = "fd-table__cell row-num";
  tr.appendChild(numTd);

  for (const { key, cls } of FIELDS) tr.appendChild(makeCell(row[key], key, cls));

  const toolsTd = document.createElement("td");
  toolsTd.className = "fd-table__cell row-tools";

  toolsTd.appendChild(iconBtn("slim-arrow-up",   "Move up",       () => moveRow(tr, -1)));
  toolsTd.appendChild(iconBtn("slim-arrow-down", "Move down",     () => moveRow(tr, +1)));
  toolsTd.appendChild(iconBtn("add",             "Insert below",  () => insertRowAfter(tr)));
  const del = iconBtn("decline", "Delete lift", () => removeRow(tr));
  del.classList.add("row-tool--danger");
  toolsTd.appendChild(del);

  tr.appendChild(toolsTd);
  return tr;
}

function appendRow(row = {}) {
  tbody.appendChild(buildRow(row));
  renumber();
  validate();
}

function insertRowAfter(tr) {
  const newTr = buildRow({});
  tr.parentNode.insertBefore(newTr, tr.nextElementSibling);
  renumber();
  validate();
  // focus the first input of the inserted row for fast entry
  newTr.querySelector("input.cell")?.focus();
}

function moveRow(tr, dir) {
  if (dir < 0 && tr.previousElementSibling) {
    tr.parentNode.insertBefore(tr, tr.previousElementSibling);
  } else if (dir > 0 && tr.nextElementSibling) {
    tr.parentNode.insertBefore(tr.nextElementSibling, tr);
  } else {
    return;
  }
  renumber();
  validate();
}

function removeRow(tr) {
  tr.remove();
  renumber();
  validate();
}

function renumber() {
  const rows = Array.from(tbody.children);
  rows.forEach((tr, i) => {
    tr.querySelector("td.row-num").textContent = String(i + 1);
    // Disable move-up on first, move-down on last
    const tools = tr.querySelectorAll(".row-tool");
    if (tools[0]) tools[0].disabled = (i === 0);
    if (tools[1]) tools[1].disabled = (i === rows.length - 1);
  });
}

function collectRows() {
  const rows = [];
  for (const tr of tbody.children) {
    const row = {};
    for (const inp of tr.querySelectorAll("input.cell")) {
      row[inp.dataset.key] = inp.value;
    }
    rows.push(row);
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Live plausibility checks
// ---------------------------------------------------------------------------

function parseTimeMin(s) {
  // returns: null (empty), NaN (invalid format), or minutes-since-midnight
  const t = (s || "").trim();
  if (!t) return null;
  const m = /^(\d{1,2}):(\d{2})$/.exec(t);
  if (!m) return NaN;
  const h = +m[1], mi = +m[2];
  if (h > 23 || mi > 59) return NaN;
  return h * 60 + mi;
}

function markInvalid(input, reason) {
  input.classList.add("cell--invalid");
  input.title = reason;
}
function clearInvalid(input) {
  input.classList.remove("cell--invalid");
  input.title = "";
}

function validate() {
  const rows = Array.from(tbody.children);
  let issues = 0;
  let prevLdg = null;
  let prevRow = null;

  for (const tr of rows) {
    const inputs = {};
    for (const inp of tr.querySelectorAll("input.cell")) {
      inputs[inp.dataset.key] = inp;
      clearInvalid(inp);
    }
    tr.classList.remove("row--issue");
    let rowBad = false;

    const to  = parseTimeMin(inputs.to.value);
    const ldg = parseTimeMin(inputs.ldg.value);

    if (Number.isNaN(to))  { markInvalid(inputs.to,  "Invalid time format — expected HH:MM"); rowBad = true; }
    if (Number.isNaN(ldg)) { markInvalid(inputs.ldg, "Invalid time format — expected HH:MM"); rowBad = true; }

    // LDG must be >= TO (same day)
    if (typeof to === "number" && typeof ldg === "number" && ldg < to) {
      markInvalid(inputs.ldg, "Landing time is before take-off time");
      rowBad = true;
    }

    // No overlap with the previous lift
    if (typeof to === "number" && typeof prevLdg === "number" && to < prevLdg) {
      markInvalid(inputs.to, "Take-off before previous lift's landing — lifts overlap");
      if (prevRow) {
        const prevLdgInp = prevRow.querySelector('input.cell[data-key="ldg"]');
        if (prevLdgInp) markInvalid(prevLdgInp, "Overlaps with next lift's take-off");
        prevRow.classList.add("row--issue");
      }
      rowBad = true;
    }

    // TIME field consistency check (warn only — non-blocking)
    const declared = parseInt((inputs.time_min.value || "").trim(), 10);
    if (typeof to === "number" && typeof ldg === "number" && ldg >= to && !Number.isNaN(declared)) {
      const computed = ldg - to;
      if (Math.abs(computed - declared) > 1) {
        markInvalid(inputs.time_min, `Duration mismatch — TO/LDG span ${computed} min, TIME says ${declared}`);
        rowBad = true;
      }
    }

    if (rowBad) {
      tr.classList.add("row--issue");
      issues++;
    }
    if (typeof ldg === "number") { prevLdg = ldg; prevRow = tr; }
  }

  // Surface the issue count on the render button without blocking submission
  renderBtn.dataset.issues = String(issues);
  if (issues > 0) {
    renderBtn.title = `${issues} plausibility issue${issues === 1 ? "" : "s"} flagged — review the table before generating.`;
  } else {
    renderBtn.title = "Persist & Render Pre-Flight Operational Manifest as SmartForm®-Compatible PDF/A-3 Document (output device LOCL)";
  }
}

// ---------------------------------------------------------------------------
// Hint chrome for no-match diagnostics
// ---------------------------------------------------------------------------

function renderCandidates(cands) {
  if (!cands || !cands.length) return "";
  const top = cands.slice(0, 5).map(c => {
    const flag = c.jump_pattern ? " — jump pattern" : "";
    const reg  = c.registration || "(unknown)";
    return `<li><code>--flarm-id ${c.address}</code> &middot; ${reg} &middot; ${c.aircraft || "?"} &middot; ${c.flight_count} flights, peak ${c.peak_alt_ft} ft${flag}</li>`;
  }).join("");
  return `<div class="candidates">OGN saw these devices today — pick one and rerun:<ul>${top}</ul></div>`;
}

// ---------------------------------------------------------------------------
// Network / event wiring
// ---------------------------------------------------------------------------

fetchBtn.addEventListener("click", async (e) => {
  e.preventDefault();
  if (!form.reportValidity()) return;
  const vals = formValues();
  setStatus("Fetching from OGN…");
  fetchBtn.disabled = true;
  try {
    const resp = await fetch("/api/fetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(vals),
    });
    const data = await resp.json();
    if (!resp.ok) {
      setStatus(data.error || `HTTP ${resp.status}`, "error");
      statusEl.insertAdjacentHTML("beforeend", renderCandidates(data.candidates));
      return;
    }
    tbody.innerHTML = "";
    for (const r of data.lifts) tbody.appendChild(buildRow(r));
    renumber();
    validate();
    tablePanel.hidden = false;
    setStatus(`Loaded ${data.lifts.length} lift(s) from ${data.airfield || vals.airport}.`, "ok");
  } catch (err) {
    setStatus("Network error: " + err.message, "error");
  } finally {
    fetchBtn.disabled = false;
  }
});

addRowBtn.addEventListener("click", () => appendRow({}));

renderBtn.addEventListener("click", async () => {
  const vals = formValues();
  const body = { ...vals, lifts: collectRows() };
  setStatus("Generating PDF…");
  renderBtn.disabled = true;
  try {
    const resp = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const text = await resp.text();
      setStatus("Render failed: " + text, "error");
      return;
    }
    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url;
    a.download = `logsheet_${vals.airport}_${vals.callsign}_${vals.date}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus(`PDF generated (${body.lifts.length} lift(s)).`, "ok");
  } catch (err) {
    setStatus("Network error: " + err.message, "error");
  } finally {
    renderBtn.disabled = false;
  }
});
