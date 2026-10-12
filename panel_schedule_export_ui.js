(() => {
  "use strict";

  // Panel Schedule Export: pick Excel workbooks, read every panel schedule sheet
  // through the backend (panel_schedule_export.py) and show it as copyable text.

  const state = {
    files: [], // { path, name, error, panels: [{ key, checked, ... }], legendMarkdown, legend, skippedSheets }
    format: "md",
    busy: false,
  };

  const byId = (id) => document.getElementById(id);

  function api() {
    return window.pywebview?.api || null;
  }

  function notify(message, duration = 4500) {
    if (typeof window.toast === "function") {
      window.toast(message, duration);
      return;
    }
    console.info(`[panel-export] ${message}`);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function setStatus(message, isError = false) {
    const status = byId("panelExportStatus");
    if (!status) return;
    status.textContent = String(message || "");
    status.classList.toggle("is-error", isError);
  }

  function setBusy(isBusy) {
    state.busy = Boolean(isBusy);
    const overlay = byId("panelExportBusy");
    if (overlay) overlay.hidden = !state.busy;
    for (const id of ["panelExportAddBtn", "panelExportEmptyAddBtn", "panelExportHidden", "panelExportClearBtn"]) {
      const control = byId(id);
      if (control) control.disabled = state.busy || (id === "panelExportClearBtn" && !state.files.length);
    }
  }

  function allPanels() {
    return state.files.flatMap((file) => file.panels || []);
  }

  function checkedPanels(file) {
    return (file.panels || []).filter((panel) => panel.checked);
  }

  function stem(name) {
    return String(name || "").replace(/\.[^.\\/]+$/, "");
  }

  // ---------------------------------------------------------------- output

  function buildMarkdown() {
    const includeLegend = byId("panelExportLegend")?.checked !== false;
    const sections = [];
    for (const file of state.files) {
      const panels = checkedPanels(file);
      if (!panels.length) continue;
      const parts = [`# ${file.name}\n`];
      for (const panel of panels) parts.push(panel.markdown.trimEnd() + "\n");
      if (includeLegend && file.legendMarkdown) parts.push(file.legendMarkdown.trimEnd() + "\n");
      sections.push(parts.join("\n"));
    }
    return sections.join("\n---\n\n");
  }

  function buildJson() {
    const includeLegend = byId("panelExportLegend")?.checked !== false;
    const files = [];
    for (const file of state.files) {
      const panels = checkedPanels(file);
      if (!panels.length) continue;
      const entry = { file: file.name, path: file.path, panels: panels.map((panel) => panel.data) };
      if (includeLegend) entry.notesLegend = file.legend;
      files.push(entry);
    }
    return files.length ? JSON.stringify({ files }, null, 2) : "";
  }

  function currentText() {
    return state.format === "json" ? buildJson() : buildMarkdown();
  }

  function defaultFileName() {
    const withPanels = state.files.filter((file) => checkedPanels(file).length);
    const base = withPanels.length === 1 ? `${stem(withPanels[0].name)} panel schedules` : "panel schedules";
    return base;
  }

  // ---------------------------------------------------------------- render

  function renderFiles() {
    const host = byId("panelExportFiles");
    if (!host) return;
    host.replaceChildren();
    if (!state.files.length) {
      host.appendChild(el("div", "pse-side-empty", "No workbooks yet."));
    }
    state.files.forEach((file, index) => {
      const row = el("div", "pse-file");
      const info = el("div", "pse-file-info");
      const name = el("div", "pse-file-name", file.name);
      name.title = file.path;
      info.appendChild(name);
      if (file.error) {
        info.appendChild(el("div", "pse-file-meta is-error", file.error));
      } else {
        const skipped = (file.skippedSheets || []).length;
        info.appendChild(
          el(
            "div",
            "pse-file-meta",
            `${file.panels.length} panel${file.panels.length === 1 ? "" : "s"}` +
              (skipped ? ` · ${skipped} sheet${skipped === 1 ? "" : "s"} skipped` : ""),
          ),
        );
        if (skipped) {
          const details = el("details", "pse-skipped");
          details.appendChild(el("summary", "", "Why skipped?"));
          const list = el("ul");
          for (const item of file.skippedSheets) {
            list.appendChild(el("li", "", `${item.sheet}: ${item.reason}`));
          }
          details.appendChild(list);
          info.appendChild(details);
        }
      }
      const remove = el("button", "pse-remove", "×");
      remove.type = "button";
      remove.title = `Remove ${file.name}`;
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.addEventListener("click", () => {
        state.files.splice(index, 1);
        renderAll();
      });
      row.append(info, remove);
      host.appendChild(row);
    });
    const clear = byId("panelExportClearBtn");
    if (clear) clear.disabled = state.busy || !state.files.length;
  }

  function renderPanels() {
    const host = byId("panelExportPanels");
    if (!host) return;
    host.replaceChildren();
    const total = allPanels().length;
    const badge = byId("panelExportPanelCount");
    if (badge) badge.textContent = String(total);
    if (!total) {
      host.appendChild(el("div", "pse-side-empty", "Panels found in your workbooks will be listed here."));
      return;
    }
    for (const file of state.files) {
      if (!file.panels?.length) continue;
      if (state.files.length > 1) host.appendChild(el("div", "pse-panel-group", file.name));
      for (const panel of file.panels) {
        const label = el("label", "pse-panel");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = panel.checked;
        box.addEventListener("change", () => {
          panel.checked = box.checked;
          renderPreview();
        });
        const text = el("span", "pse-panel-text");
        const title = el("span", "pse-panel-title");
        title.appendChild(el("span", "pse-panel-name", `Panel ${panel.name}`));
        if (panel.status) title.appendChild(el("span", "pse-chip", panel.status));
        if (panel.hidden) title.appendChild(el("span", "pse-chip is-muted", "hidden"));
        if (panel.warningCount) {
          const warn = el("span", "pse-chip is-warn", `${panel.warningCount} check${panel.warningCount === 1 ? "" : "s"}`);
          warn.title = "This panel has warnings, shown at the bottom of its text.";
          title.appendChild(warn);
        }
        text.appendChild(title);
        const detail = [panel.description, panel.summary].filter(Boolean).join(" · ");
        if (detail) text.appendChild(el("span", "pse-panel-detail", detail));
        const sheet = el("span", "pse-panel-sheet", `Sheet: ${panel.sheet}`);
        text.appendChild(sheet);
        label.append(box, text);
        host.appendChild(label);
      }
    }
  }

  function renderPreview() {
    const preview = byId("panelExportPreview");
    const empty = byId("panelExportEmpty");
    const copyBtn = byId("panelExportCopyBtn");
    const saveBtn = byId("panelExportSaveBtn");
    const text = currentText();
    const hasPanels = allPanels().length > 0;
    if (preview) {
      preview.value = text;
      preview.hidden = !hasPanels;
      preview.scrollTop = 0;
    }
    if (empty) {
      empty.hidden = hasPanels || state.busy;
      const title = empty.querySelector(".pse-empty-title");
      if (title) title.textContent = state.files.length ? "No panel schedules found" : "No workbook loaded";
    }
    const canUse = Boolean(text);
    if (copyBtn) copyBtn.disabled = !canUse;
    if (saveBtn) saveBtn.disabled = !canUse;
    const selected = allPanels().filter((panel) => panel.checked).length;
    if (hasPanels) {
      const lines = text ? text.split("\n").length : 0;
      setStatus(selected ? `${selected} of ${allPanels().length} panels · ${lines.toLocaleString()} lines` : "No panels selected.");
    }
  }

  function renderFormat() {
    const isJson = state.format === "json";
    const md = byId("panelExportFormatMd");
    const json = byId("panelExportFormatJson");
    md?.classList.toggle("is-active", !isJson);
    json?.classList.toggle("is-active", isJson);
    md?.setAttribute("aria-pressed", String(!isJson));
    json?.setAttribute("aria-pressed", String(isJson));
  }

  function renderAll() {
    renderFiles();
    renderPanels();
    renderFormat();
    renderPreview();
  }

  // ---------------------------------------------------------------- actions

  function panelId(file, panel) {
    return `${String(file.path).toLowerCase()}|${panel.sheet}`;
  }

  async function extract(paths) {
    if (!api()?.export_panel_schedule_files) {
      notify("Panel Schedule Export is available in the desktop app.");
      return null;
    }
    const response = await api().export_panel_schedule_files(paths, byId("panelExportHidden")?.checked === true);
    if (response?.status !== "success") {
      throw new Error(response?.message || "Could not read the selected workbooks.");
    }
    return response.files || [];
  }

  function adopt(fresh, previous) {
    const wasChecked = new Map();
    for (const file of previous) {
      for (const panel of file.panels || []) wasChecked.set(panelId(file, panel), panel.checked);
    }
    for (const file of fresh) {
      file.panels = file.panels || [];
      for (const panel of file.panels) {
        const prior = wasChecked.get(panelId(file, panel));
        panel.checked = prior === undefined ? true : prior;
      }
    }
    return fresh;
  }

  async function addFiles() {
    if (state.busy) return;
    if (!api()?.select_files) {
      notify("Panel Schedule Export is available in the desktop app.");
      return;
    }
    try {
      const selection = await api().select_files({
        allow_multiple: true,
        file_types: ["Excel Files (*.xlsx;*.xls)"],
      });
      const picked = Array.isArray(selection?.paths) ? selection.paths : selection?.path ? [selection.path] : [];
      if (selection?.status === "cancelled" || !picked.length) return;
      const known = new Set(state.files.map((file) => String(file.path).toLowerCase()));
      const paths = picked.filter((path) => !known.has(String(path).toLowerCase()));
      if (!paths.length) {
        setStatus("Those workbooks are already loaded.");
        return;
      }
      setBusy(true);
      setStatus("");
      const fresh = adopt(await extract(paths), state.files);
      state.files.push(...fresh);
      const failed = fresh.filter((file) => file.error).length;
      renderAll();
      if (failed) setStatus(`${failed} workbook${failed === 1 ? "" : "s"} could not be read.`, true);
    } catch (error) {
      setStatus(error?.message || "Failed to read workbooks.", true);
      notify(error?.message || "Failed to read workbooks.");
    } finally {
      setBusy(false);
      renderAll();
    }
  }

  async function reextractAll() {
    if (state.busy || !state.files.length) return;
    try {
      setBusy(true);
      const previous = state.files;
      state.files = adopt(await extract(previous.map((file) => file.path)), previous);
    } catch (error) {
      setStatus(error?.message || "Failed to read workbooks.", true);
    } finally {
      setBusy(false);
      renderAll();
    }
  }

  async function copyText() {
    const text = currentText();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch (_error) {
      const preview = byId("panelExportPreview");
      preview?.focus();
      preview?.select();
      if (!document.execCommand("copy")) {
        notify("Could not copy. Select the text and press Ctrl+C.");
        return;
      }
    }
    setStatus("Copied to clipboard.");
    notify("Copied panel schedule text.", 2500);
  }

  async function saveFile() {
    const text = currentText();
    if (!text || !api()?.save_panel_schedule_export) return;
    try {
      const response = await api().save_panel_schedule_export(text, defaultFileName(), state.format);
      if (response?.status === "success") {
        setStatus(`Saved ${response.path}`);
        notify("Saved panel schedule export.", 3000);
      } else if (response?.status === "error") {
        throw new Error(response.message || "Could not save the file.");
      }
    } catch (error) {
      setStatus(error?.message || "Could not save the file.", true);
      notify(error?.message || "Could not save the file.");
    }
  }

  function setAllChecked(value) {
    for (const panel of allPanels()) panel.checked = value;
    renderPanels();
    renderPreview();
  }

  function setFormat(format) {
    state.format = format;
    renderFormat();
    renderPreview();
  }

  function dialog() {
    return byId("panelExportDlg");
  }

  function openPanelScheduleExport() {
    const dlg = dialog();
    if (!dlg) return;
    if (!dlg.open) dlg.showModal();
    renderAll();
  }

  function closePanelScheduleExport() {
    const dlg = dialog();
    if (dlg?.open) dlg.close();
  }

  function bindEvents() {
    const card = byId("toolPanelScheduleExport");
    if (card) {
      card.addEventListener("click", openPanelScheduleExport);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openPanelScheduleExport();
        }
      });
    }
    byId("panelExportCloseBtn")?.addEventListener("click", closePanelScheduleExport);
    byId("panelExportAddBtn")?.addEventListener("click", addFiles);
    byId("panelExportEmptyAddBtn")?.addEventListener("click", addFiles);
    byId("panelExportClearBtn")?.addEventListener("click", () => {
      state.files = [];
      setStatus("");
      renderAll();
    });
    byId("panelExportHidden")?.addEventListener("change", reextractAll);
    byId("panelExportLegend")?.addEventListener("change", renderPreview);
    byId("panelExportSelectAllBtn")?.addEventListener("click", () => setAllChecked(true));
    byId("panelExportSelectNoneBtn")?.addEventListener("click", () => setAllChecked(false));
    byId("panelExportFormatMd")?.addEventListener("click", () => setFormat("md"));
    byId("panelExportFormatJson")?.addEventListener("click", () => setFormat("json"));
    byId("panelExportCopyBtn")?.addEventListener("click", copyText);
    byId("panelExportSaveBtn")?.addEventListener("click", saveFile);
  }

  function initialize() {
    bindEvents();
    renderAll();
    window.openPanelScheduleExport = openPanelScheduleExport;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
