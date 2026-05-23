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

function makeCell(value, key, extraCls) {
  const td = document.createElement("td");
  td.className = "fd-table__cell";
  const inp = document.createElement("input");
  inp.type = "text";
  inp.dataset.key = key;
  inp.className = "cell" + (extraCls ? " " + extraCls : "");
  inp.value = value ?? "";
  td.appendChild(inp);
  return td;
}

function renumber() {
  Array.from(tbody.children).forEach((tr, i) => {
    tr.querySelector("td.row-num").textContent = String(i + 1);
  });
}

function addRow(row = {}) {
  const tr = document.createElement("tr");
  tr.className = "fd-table__row";

  const numTd = document.createElement("td");
  numTd.className = "fd-table__cell row-num";
  tr.appendChild(numTd);

  for (const { key, cls } of FIELDS) tr.appendChild(makeCell(row[key], key, cls));

  const delTd = document.createElement("td");
  delTd.className = "fd-table__cell row-actions";
  const del = document.createElement("button");
  del.type = "button";
  del.className = "row-del";
  del.title = "Delete this lift";
  del.setAttribute("aria-label", "Delete lift");
  del.innerHTML = '<i class="sap-icon--decline" aria-hidden="true"></i>';
  del.addEventListener("click", () => {
    tr.remove();
    renumber();
  });
  delTd.appendChild(del);
  tr.appendChild(delTd);

  tbody.appendChild(tr);
  renumber();
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

function renderCandidates(cands) {
  if (!cands || !cands.length) return "";
  const top = cands.slice(0, 5).map(c => {
    const flag = c.jump_pattern ? " — jump pattern" : "";
    const reg  = c.registration || "(unknown)";
    return `<li><code>--flarm-id ${c.address}</code> &middot; ${reg} &middot; ${c.aircraft || "?"} &middot; ${c.flight_count} flights, peak ${c.peak_alt_ft} ft${flag}</li>`;
  }).join("");
  return `<div class="candidates">OGN saw these devices today — pick one and rerun:<ul>${top}</ul></div>`;
}

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
    for (const r of data.lifts) addRow(r);
    tablePanel.hidden = false;
    setStatus(`Loaded ${data.lifts.length} lift(s) from ${data.airfield || vals.airport}.`, "ok");
  } catch (err) {
    setStatus("Network error: " + err.message, "error");
  } finally {
    fetchBtn.disabled = false;
  }
});

addRowBtn.addEventListener("click", () => addRow({}));

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
