"use strict";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );
const fmt = (value) =>
  value == null
    ? "—"
    : typeof value === "number"
      ? value !== 0 && Math.abs(value) < 0.0001
        ? value.toExponential(3)
        : new Intl.NumberFormat("es-ES", { maximumFractionDigits: 4 }).format(
            value,
          )
      : String(value);
let state = {
  variables: [],
  history: [],
  data: { columns: [], rows: [] },
  rows: 0,
  filteredRows: 0,
  page: 0,
};
let currentView = "data",
  busy = false,
  importedFile = null,
  editingCell = null,
  historyIndex = -1,
  searchTimer;
const viewCopy = {
  data: [
    "Explorador de datos",
    "Tus datos, con perspectiva.",
    "Del primer vistazo a la próxima conclusión, en un mismo lugar.",
  ],
  results: [
    "Resultados",
    "Las respuestas toman forma.",
    "Resultados claros, métodos explícitos y comandos reproducibles.",
  ],
  history: [
    "Historial",
    "Cada paso cuenta.",
    "Revisa tu recorrido, recupera comandos y continúa donde lo dejaste.",
  ],
  help: [
    "Guía de comandos",
    "Una idea. Un comando.",
    "Una referencia práctica para explorar, transformar y analizar.",
  ],
};
function toast(message, error = false) {
  $("#toast").textContent = message;
  $("#toast").className = error ? "error" : "";
  $("#toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("#toast").hidden = true), 5500);
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = "No se ha podido conectar con el servidor.";
    try {
      const body = await response.json();
      message =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
const jsonOptions = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});
function switchView(view) {
  currentView = view;
  $$(".view").forEach((el) => (el.hidden = el.id !== `${view}-view`));
  $$(".nav-item").forEach((el) =>
    el.classList.toggle("active", el.dataset.view === view),
  );
  const [breadcrumb, title, subtitle] = viewCopy[view];
  $("#breadcrumb-view").textContent = breadcrumb;
  $("#page-title").textContent = title;
  $("#page-subtitle").textContent = subtitle;
}
function tableHTML(data, extraClass = "") {
  return `<table class="${extraClass}"><thead><tr>${data.columns.map((c) => `<th>${escapeHTML(c)}</th>`).join("")}</tr></thead><tbody>${data.rows.map((row) => `<tr>${row.map((v) => `<td class="${typeof v === "string" ? "text-cell" : ""}">${escapeHTML(fmt(v))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function renderVariables() {
  const query = $("#variable-search").value.toLowerCase();
  $("#variable-list").innerHTML = state.variables
    .filter((v) => v.name.toLowerCase().includes(query))
    .map(
      (v) =>
        `<button class="variable-item" data-variable="${escapeHTML(v.name)}" title="${v.missing} valores ausentes · ${v.unique} valores únicos. Clic para insertar en la consola."><span class="type-tag ${v.type === "text" ? "text" : ""}">${v.type === "number" ? "#" : "Aa"}</span>${escapeHTML(v.name)}</button>`,
    )
    .join("");
}
function renderTable() {
  const { columns, rows } = state.data;
  $("#data-table").innerHTML =
    `<table><thead><tr><th class="row-index">#</th>${columns.map((c, i) => `<th class="${state.variables[i]?.type === "text" ? "text-cell" : ""}"><span class="type-tag ${state.variables[i]?.type === "text" ? "text" : ""}">${state.variables[i]?.type === "number" ? "#" : "Aa"}</span> ${escapeHTML(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((row, i) => `<tr><td class="row-index">${state.indices[i] + 1}</td>${row.map((v, j) => `<td tabindex="0" data-row="${state.indices[i]}" data-column="${escapeHTML(columns[j])}" class="${typeof v === "string" ? "text-cell" : ""} ${v == null ? "missing" : ""}" aria-label="${escapeHTML(columns[j])}, fila ${state.indices[i] + 1}: ${escapeHTML(fmt(v))}. Enter para editar">${escapeHTML(fmt(v))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  const start = state.filteredRows ? state.page * 100 + 1 : 0;
  $("#table-info").textContent =
    `${fmt(start)}–${fmt(Math.min((state.page + 1) * 100, state.filteredRows))} de ${fmt(state.filteredRows)} observaciones`;
  $("#page-info").textContent =
    `${state.page + 1} / ${Math.max(1, Math.ceil(state.filteredRows / 100))}`;
  $("#prev-page").disabled = state.page === 0;
  $("#next-page").disabled = (state.page + 1) * 100 >= state.filteredRows;
}
function chartHTML(chart) {
  const width = 760,
    height = 340,
    pad = { l: 68, r: 25, t: 25, b: 57 },
    plotW = width - pad.l - pad.r,
    plotH = height - pad.t - pad.b;
  if (!chart.points?.length) return "";
  let xmin,
    xmax,
    ymax,
    ymin = 0;
  if (chart.type === "histogram") {
    xmin = chart.points[0][0];
    xmax = chart.points.at(-1)[1];
    ymax = Math.max(...chart.points.map((p) => p[2]));
  } else {
    xmin = Math.min(...chart.points.map((p) => p[0]));
    xmax = Math.max(...chart.points.map((p) => p[0]));
    ymin = Math.min(...chart.points.map((p) => p[1]));
    ymax = Math.max(...chart.points.map((p) => p[1]));
  }
  if (xmax === xmin) {
    xmin -= 0.5;
    xmax += 0.5;
  }
  if (ymax === ymin) {
    ymin -= 0.5;
    ymax += 0.5;
  }
  const x = (v) => pad.l + ((v - xmin) / (xmax - xmin)) * plotW,
    y = (v) => pad.t + plotH - ((v - ymin) / (ymax - ymin)) * plotH;
  let content = "";
  for (let i = 0; i <= 5; i++) {
    const vx = xmin + ((xmax - xmin) * i) / 5,
      vy = ymin + ((ymax - ymin) * i) / 5;
    content += `<line class="grid" x1="${pad.l}" x2="${width - pad.r}" y1="${y(vy)}" y2="${y(vy)}"/><text x="${pad.l - 12}" y="${y(vy) + 4}" text-anchor="end">${escapeHTML(fmt(Number(vy.toPrecision(3))))}</text><text x="${x(vx)}" y="${height - pad.b + 22}" text-anchor="middle">${escapeHTML(fmt(Number(vx.toPrecision(3))))}</text>`;
  }
  content += chart.points
    .map((p) =>
      chart.type === "histogram"
        ? `<rect class="mark" x="${x(p[0]) + 1}" y="${y(p[2])}" width="${Math.max(0.1, x(p[1]) - x(p[0]) - 2)}" height="${y(0) - y(p[2])}"><title>${escapeHTML(fmt(p[0]))}–${escapeHTML(fmt(p[1]))}: ${p[2]}</title></rect>`
        : `<circle class="mark" cx="${x(p[0])}" cy="${y(p[1])}" r="3"><title>${escapeHTML(fmt(p[0]))}, ${escapeHTML(fmt(p[1]))}</title></circle>`,
    )
    .join("");
  content += `<text class="axis-title" x="${pad.l + plotW / 2}" y="${height - 8}" text-anchor="middle">${escapeHTML(chart.x)}</text><text class="axis-title" transform="translate(16 ${pad.t + plotH / 2}) rotate(-90)" text-anchor="middle">${escapeHTML(chart.y)}</text>`;
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHTML(chart.type === "histogram" ? "Histograma de " + chart.x : chart.y + " frente a " + chart.x)}">${content}</svg>`;
}
function renderResults() {
  const results = state.history
    .map((h, i) => ({ ...h, index: i }))
    .filter((h) => h.result && !h.command.startsWith("*"))
    .reverse();
  $("#results-list").innerHTML = results.length
    ? results
        .map(
          (h) =>
            `<article class="result-card"><div class="result-command">› ${escapeHTML(h.command)}</div><h2>${escapeHTML(h.result.title)}</h2>${
              h.result.metrics
                ? `<div class="metrics">${Object.entries(h.result.metrics)
                    .map(
                      ([k, v]) =>
                        `<div class="metric"><small>${escapeHTML(k)}</small><strong>${escapeHTML(fmt(v))}</strong></div>`,
                    )
                    .join("")}</div>`
                : ""
            }${h.result.table ? `<div class="table-scroll">${tableHTML(h.result.table)}</div>` : ""}${h.result.chart ? chartHTML(h.result.chart) : ""}${h.result.message ? `<p>${escapeHTML(h.result.message)}</p>` : ""}${h.result.chart ? `<button class="button small" data-download-chart="${h.index}">↓ Descargar gráfico SVG</button>` : ""}</article>`,
        )
        .join("")
    : '<div class="result-empty">Tu siguiente hallazgo empieza aquí. Ejecuta un análisis desde el explorador o la consola.</div>';
}
function renderHistory() {
  $("#history-list").innerHTML = state.history.length
    ? state.history
        .map(
          (h, i) =>
            `<article class="history-entry ${h.error ? "failed" : ""}"><div><span class="history-number">${String(i + 1).padStart(2, "0")}</span><code>${escapeHTML(h.command)}</code><small>${escapeHTML(h.error || h.result?.title || "Acción registrada")}</small></div>${!h.command.startsWith("*") ? `<button class="button small" data-reuse="${i}">Reutilizar ↗</button>` : ""}</article>`,
        )
        .reverse()
        .join("")
    : '<div class="result-empty">Aquí aparecerán las importaciones, ediciones y comandos de esta sesión.</div>';
}
function render(next) {
  state = next;
  historyIndex = -1;
  const hasData = state.variables.length > 0;
  $("#empty-state").hidden = hasData;
  $("#data-workspace").hidden = !hasData;
  $("#rows-stat").textContent = hasData ? fmt(state.rows) : "—";
  $("#cols-stat").textContent = hasData ? fmt(state.variables.length) : "—";
  $("#missing-stat").textContent = hasData ? fmt(state.missing) : "—";
  const analyses = state.history.filter(
    (h) => h.result && !h.command.startsWith("*"),
  ).length;
  $("#analysis-stat").textContent = fmt(analyses);
  $("#result-count").textContent = analyses;
  $("#dataset-name").textContent = state.name;
  $("#dataset-short").textContent = hasData ? state.name : "Sin archivo";
  $("#dataset-size").textContent = hasData
    ? `${fmt(state.rows)} filas · ${state.variables.length} variables`
    : "Importa datos para comenzar";
  $("#var-count").textContent = state.variables.length;
  $("#undo").disabled = !state.canUndo;
  renderVariables();
  renderTable();
  renderResults();
  renderHistory();
}
async function refresh(page = 0) {
  render(
    await api(
      `/api/state?page=${page}&search=${encodeURIComponent($("#table-search").value)}`,
    ),
  );
}
async function execute(command) {
  if (busy || !command.trim()) return false;
  busy = true;
  $("#execute").disabled = true;
  $("#console-status").textContent = "Calculando…";
  try {
    const result = await api("/api/command", jsonOptions("POST", { command }));
    $("#table-search").value = "";
    render(result.state);
    $("#command").value = "";
    $("#console-status").textContent = `✓ ${result.result.title}`;
    switchView("results");
    return true;
  } catch (error) {
    toast(error.message, true);
    $("#console-status").textContent =
      "Revisa el comando e inténtalo de nuevo.";
    await refresh().catch(() => {});
    return false;
  } finally {
    busy = false;
    $("#execute").disabled = false;
  }
}
function selectedValues(id) {
  return [...(document.getElementById(id)?.selectedOptions || [])].map(
    (o) => o.value,
  );
}
function optionsHTML(numeric = false) {
  return state.variables
    .filter((v) => !numeric || v.type === "number")
    .map(
      (v) =>
        `<option value="${escapeHTML(v.name)}">${escapeHTML(v.name)}</option>`,
    )
    .join("");
}
function analysisFields() {
  const type = $("#analysis-type").value;
  let html = "";
  if (["summarize", "correlate"].includes(type))
    html = `<label>Variables (Ctrl o ⌘ para seleccionar varias)<select id="analysis-vars" multiple>${optionsHTML(true)}</select></label><p class="field-help">${type === "summarize" ? "Sin selección se analizarán todas las variables numéricas." : "Selecciona al menos dos variables."}</p>`;
  else if (type === "regress")
    html = `<label>Variable dependiente (Y)<select id="analysis-y">${optionsHTML(true)}</select></label><label>Variables explicativas (X)<select id="analysis-vars" multiple>${optionsHTML(true)}</select></label><label class="check-row"><input id="analysis-robust" type="checkbox" checked>Errores estándar robustos (HC1)</label>`;
  else if (type === "scatter")
    html = `<label>Eje vertical (Y)<select id="analysis-y">${optionsHTML(true)}</select></label><label>Eje horizontal (X)<select id="analysis-x">${optionsHTML(true)}</select></label>`;
  else if (type === "ttest")
    html = `<label>Variable numérica<select id="analysis-y">${optionsHTML(true)}</select></label><label>Variable de agrupación (dos grupos)<select id="analysis-group">${optionsHTML()}</select></label>`;
  else
    html = `<label>Variable<select id="analysis-y">${optionsHTML(type === "histogram")}</select></label>`;
  $("#analysis-fields").innerHTML = html;
  $("#analysis-error").textContent = "";
  updatePreview();
}
function updatePreview() {
  const type = $("#analysis-type").value;
  let cmd = type;
  if (["summarize", "correlate"].includes(type))
    cmd += " " + selectedValues("analysis-vars").join(" ");
  else if (type === "regress")
    cmd += ` ${$("#analysis-y")?.value || ""} ${selectedValues("analysis-vars").join(" ")}${$("#analysis-robust")?.checked ? ", robust" : ""}`;
  else if (type === "scatter")
    cmd += ` ${$("#analysis-y")?.value || ""} ${$("#analysis-x")?.value || ""}`;
  else if (type === "ttest")
    cmd += ` ${$("#analysis-y")?.value || ""}, by(${$("#analysis-group")?.value || ""})`;
  else cmd += " " + ($("#analysis-y")?.value || "");
  if ($("#analysis-condition").value.trim())
    cmd += " if " + $("#analysis-condition").value.trim();
  $("#analysis-preview").textContent = cmd.trim();
}
function openAnalysis(type = "summarize") {
  if (!state.variables.length) {
    toast("Importa datos o carga el ejemplo para analizar.");
    return;
  }
  $("#analysis-type").value = type;
  $("#analysis-condition").value = "";
  analysisFields();
  $("#analysis-dialog").showModal();
}
async function chooseFile(file) {
  if (!file) return;
  importedFile = file;
  $("#import-error").textContent = "";
  $("#import-submit").disabled = true;
  $("#import-options").hidden = true;
  if (file.size > 20 * 1024 * 1024) {
    $("#import-error").textContent = "El archivo supera el límite de 20 MB.";
    return;
  }
  if (!/\.(xlsx|csv|tsv)$/i.test(file.name)) {
    $("#import-error").textContent = "Selecciona un archivo XLSX, CSV o TSV.";
    return;
  }
  const excel = /\.xlsx$/i.test(file.name);
  $("#sheet-label").hidden = !excel;
  $("#csv-options").hidden = excel;
  $("#selected-file").textContent = file.name;
  try {
    if (excel) {
      const form = new FormData();
      form.append("file", file);
      const data = await api("/api/sheets", { method: "POST", body: form });
      $("#sheet-select").innerHTML = data.sheets
        .map((s) => `<option>${escapeHTML(s)}</option>`)
        .join("");
    }
    $("#import-options").hidden = false;
    $("#import-submit").disabled = false;
  } catch (error) {
    $("#import-error").textContent = error.message;
  }
}
function downloadBlob(content, name, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function exportFile(kind) {
  try {
    const response = await fetch("/api/export/" + kind);
    if (!response.ok) throw new Error("No se pudo exportar el archivo.");
    const blob = await response.blob();
    const name = {
      project: "proyecto.studio.json",
      do: "analisis.do",
      csv: "datos.csv",
      xlsx: "datos.xlsx",
    }[kind];
    downloadBlob(blob, name, blob.type);
  } catch (error) {
    toast(error.message, true);
  }
}
function openEdit(cell) {
  editingCell = { row: Number(cell.dataset.row), column: cell.dataset.column };
  const i = state.indices.indexOf(editingCell.row),
    j = state.data.columns.indexOf(editingCell.column);
  $("#edit-title").textContent =
    `${editingCell.column} · fila ${editingCell.row + 1}`;
  $("#edit-value").value = state.data.rows[i][j] ?? "";
  $("#edit-error").textContent = "";
  $("#edit-dialog").showModal();
  $("#edit-value").select();
}
document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-view]");
  if (nav) switchView(nav.dataset.view);
  const analysis = event.target.closest("[data-analysis]");
  if (analysis) openAnalysis(analysis.dataset.analysis);
  const variable = event.target.closest("[data-variable]");
  if (variable) {
    $("#command").value +=
      ($("#command").value.endsWith(" ") || !$("#command").value ? "" : " ") +
      variable.dataset.variable;
    $("#command").focus();
  }
  const reuse = event.target.closest("[data-reuse]");
  if (reuse) {
    $("#command").value = state.history[Number(reuse.dataset.reuse)].command;
    $("#command").focus();
  }
  const chart = event.target.closest("[data-download-chart]");
  if (chart) {
    const result = state.history[Number(chart.dataset.downloadChart)].result;
    let svg = chartHTML(result.chart).replace(
      "<svg ",
      '<svg xmlns="http://www.w3.org/2000/svg" ',
    );
    svg = svg
      .replaceAll('class="mark"', 'fill="#4a9b7b" opacity="0.75" class="mark"')
      .replaceAll('class="grid"', 'stroke="#e8efea" class="grid"');
    downloadBlob(svg, "grafico.svg", "image/svg+xml");
  }
});
$("#variable-search").addEventListener("input", renderVariables);
$("#command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  execute($("#command").value);
});
$("#command").addEventListener("keydown", (event) => {
  if (!["ArrowUp", "ArrowDown"].includes(event.key)) return;
  const commands = state.history
    .filter((h) => !h.command.startsWith("*"))
    .map((h) => h.command)
    .reverse();
  event.preventDefault();
  historyIndex = Math.min(
    commands.length - 1,
    Math.max(-1, historyIndex + (event.key === "ArrowUp" ? 1 : -1)),
  );
  $("#command").value = commands[historyIndex] || "";
});
$("#console-help").onclick = () => switchView("help");
$("#analysis-open").onclick = () => openAnalysis();
$("#analysis-type").onchange = analysisFields;
$("#analysis-fields").addEventListener("change", updatePreview);
$("#analysis-condition").oninput = updatePreview;
$("#analysis-run").onclick = async () => {
  const button = $("#analysis-run");
  button.disabled = true;
  try {
    if (await execute($("#analysis-preview").textContent))
      $("#analysis-dialog").close();
    else
      $("#analysis-error").textContent =
        "Revisa la selección de variables y el mensaje de error.";
  } finally {
    button.disabled = false;
  }
};
for (const id of ["import-open", "empty-import"])
  document.getElementById(id).onclick = () => $("#import-dialog").showModal();
$("#import-file").onchange = (event) => chooseFile(event.target.files[0]);
$("#drop-zone").addEventListener("dragover", (event) => event.preventDefault());
$("#drop-zone").addEventListener("drop", (event) => {
  event.preventDefault();
  chooseFile(event.dataTransfer.files[0]);
});
$("#import-submit").onclick = async () => {
  if (!importedFile) return;
  $("#import-submit").disabled = true;
  $("#import-error").textContent = "";
  const form = new FormData();
  form.append("file", importedFile);
  const params = new URLSearchParams({
    sheet: /\.xlsx$/i.test(importedFile.name) ? $("#sheet-select").value : "",
    delimiter: $("#delimiter").value === "tab" ? "\t" : $("#delimiter").value,
    decimal: $("#decimal").value,
  });
  try {
    const data = await api("/api/import?" + params, {
      method: "POST",
      body: form,
    });
    $("#table-search").value = "";
    render(data);
    $("#import-dialog").close();
    switchView("data");
    toast("Datos importados. Ya puedes empezar a explorar.");
  } catch (error) {
    $("#import-error").textContent = error.message;
  } finally {
    $("#import-submit").disabled = false;
  }
};
$("#demo").onclick = async () => {
  const button = $("#demo");
  button.disabled = true;
  try {
    render(await api("/api/demo", { method: "POST" }));
    toast("Ejemplo sintético cargado: 240 observaciones del mercado laboral.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
};
$("#undo").onclick = async () => {
  if (await execute("undo")) switchView("data");
};
$("#export-kind").onchange = (event) => {
  if (event.target.value) exportFile(event.target.value);
  event.target.value = "";
};
$("#save-project").onclick = () => exportFile("project");
$("#history-view a[download]").onclick = (event) => {
  event.preventDefault();
  exportFile("do");
};
$("#open-project").onclick = () => $("#project-file").click();
$("#project-file").onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    render(await api("/api/project", { method: "POST", body: form }));
    $("#table-search").value = "";
    switchView("data");
    toast("Proyecto restaurado con sus datos e historial.");
  } catch (error) {
    toast(error.message, true);
  }
  event.target.value = "";
};
$("#table-search").oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(
    () => refresh().catch((e) => toast(e.message, true)),
    250,
  );
};
$("#prev-page").onclick = () =>
  refresh(state.page - 1).catch((e) => toast(e.message, true));
$("#next-page").onclick = () =>
  refresh(state.page + 1).catch((e) => toast(e.message, true));
$("#data-table").addEventListener("dblclick", (event) => {
  const cell = event.target.closest("[data-row]");
  if (cell) openEdit(cell);
});
$("#data-table").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    const cell = event.target.closest("[data-row]");
    if (cell) openEdit(cell);
  }
});
$("#edit-close").onclick = () => $("#edit-dialog").close();
$("#edit-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    render(
      await api(
        "/api/cell",
        jsonOptions("PATCH", { ...editingCell, value: $("#edit-value").value }),
      ),
    );
    $("#table-search").value = "";
    $("#edit-dialog").close();
    toast("Celda actualizada. Puedes deshacer el cambio.");
  } catch (error) {
    $("#edit-error").textContent = error.message;
  }
};
async function init() {
  try {
    await refresh();
    const data = await api("/api/help");
    $("#help-content").innerHTML =
      `<div class="data-panel table-scroll">${tableHTML(data.table, "help-table")}</div>`;
  } catch (error) {
    toast(error.message, true);
    $("#console-status").textContent =
      "No se pudo conectar. Comprueba que el servidor está en marcha.";
  }
}
init();
