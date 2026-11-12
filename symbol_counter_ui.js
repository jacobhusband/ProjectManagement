(() => {
  "use strict";

  const COLORS = [
    "#10b981",
    "#3b82f6",
    "#f59e0b",
    "#ec4899",
    "#8b5cf6",
    "#06b6d4",
    "#ef4444",
    "#84cc16",
  ];

  const state = {
    session: null,
    currentPageId: "",
    image: null,
    imageLoadToken: 0,
    symbols: [],
    activeSymbolId: "",
    selectedMatchId: "",
    selection: null,
    selectionDraft: null,
    interaction: null,
    zoom: 1,
    spaceDown: false,
    mode: "select",
    busy: false,
  };

  const byId = (id) => document.getElementById(id);

  function notify(message, duration = 4500) {
    if (typeof window.toast === "function") {
      window.toast(message, duration);
      return;
    }
    console.info(`[symbol-counter] ${message}`);
  }

  function api() {
    return window.pywebview?.api || null;
  }

  function activePage() {
    return state.session?.pages?.find((page) => page.id === state.currentPageId) || null;
  }

  function activeSymbol() {
    return state.symbols.find((symbol) => symbol.id === state.activeSymbolId) || null;
  }

  function setStatus(message, isError = false) {
    const el = byId("symbolCounterStatus");
    if (!el) return;
    el.textContent = String(message || "");
    el.classList.toggle("is-error", isError);
  }

  function setBusy(isBusy, title = "Processing drawings…", detail = "This can take a moment on large sets.") {
    state.busy = Boolean(isBusy);
    const overlay = byId("symbolCounterBusy");
    if (overlay) overlay.hidden = !state.busy;
    const titleEl = byId("symbolCounterBusyTitle");
    if (titleEl) titleEl.textContent = title;
    const detailEl = byId("symbolCounterBusyDetail");
    if (detailEl) detailEl.textContent = detail;
    const runBtn = byId("symbolCounterRunBtn");
    if (runBtn) runBtn.disabled = state.busy;
    const loadBtn = byId("symbolCounterLoadBtn");
    if (loadBtn) loadBtn.disabled = state.busy;
    const clearAllBtn = byId("symbolCounterClearAllBtn");
    if (clearAllBtn) clearAllBtn.disabled = state.busy || !state.symbols.length;
  }

  function showDialog() {
    const dialog = byId("symbolCounterDlg");
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    if (state.image) requestAnimationFrame(fitDrawing);
  }

  function openSymbolCounter() {
    showDialog();
    if (!state.session) {
      setStatus("Load PDF drawings, then drag a box around one symbol.");
    }
  }

  function closeSymbolCounter() {
    const dialog = byId("symbolCounterDlg");
    if (dialog?.open) dialog.close();
  }

  function resetSelection() {
    state.selection = null;
    state.selectionDraft = null;
    renderSelectionControls();
    drawCanvas();
  }

  function resetSessionUi() {
    state.currentPageId = "";
    state.image = null;
    state.symbols = [];
    state.activeSymbolId = "";
    state.selectedMatchId = "";
    state.selection = null;
    state.selectionDraft = null;
    state.mode = "select";
    const shell = byId("symbolCounterCanvasShell");
    if (shell) shell.hidden = true;
    const empty = byId("symbolCounterEmpty");
    if (empty) empty.hidden = false;
    renderAll();
  }

  async function loadDocuments() {
    if (state.busy) return;
    if (!api()?.select_files || !api()?.prepare_symbol_count_documents) {
      notify("Symbol Counter is available in the desktop app.");
      return;
    }
    if (state.symbols.length && !window.confirm("Load a new drawing set and clear the current counts?")) {
      return;
    }
    try {
      const selection = await api().select_files({
        allow_multiple: true,
        file_types: ["PDF Files (*.pdf)"],
      });
      const paths = Array.isArray(selection?.paths)
        ? selection.paths
        : selection?.path
          ? [selection.path]
          : [];
      if (selection?.status === "cancelled" || !paths.length) return;

      setBusy(true, "Opening drawing set…", "Reading page sizes and preparing the takeoff workspace.");
      const previousSessionId = state.session?.sessionId || "";
      const response = await api().prepare_symbol_count_documents(paths);
      if (response?.status !== "success") {
        throw new Error(response?.message || "Could not open the selected PDFs.");
      }
      if (previousSessionId && api()?.close_symbol_count_session) {
        api().close_symbol_count_session(previousSessionId).catch(() => {});
      }
      resetSessionUi();
      state.session = response.data;
      renderAll();
      const firstPage = state.session?.pages?.[0];
      if (firstPage) await loadPage(firstPage.id, { fit: true });
      setStatus(`${state.session.pageCount} page${state.session.pageCount === 1 ? "" : "s"} ready. Drag a box around one symbol.`);
    } catch (error) {
      setStatus(error?.message || "Failed to load drawings.", true);
      notify(error?.message || "Failed to load drawings.");
    } finally {
      setBusy(false);
    }
  }

  function loadImage(dataUrl) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("The rendered drawing image could not be displayed."));
      image.src = dataUrl;
    });
  }

  async function loadPage(pageId, options = {}) {
    if (!state.session || !pageId || !api()?.get_symbol_count_page) return;
    const page = state.session.pages.find((item) => item.id === pageId);
    if (!page) return;
    const token = ++state.imageLoadToken;
    state.currentPageId = pageId;
    state.selection = null;
    state.selectionDraft = null;
    state.selectedMatchId = "";
    renderAll();
    setBusy(true, "Rendering drawing…", `${page.documentName} · ${page.label}`);
    try {
      const response = await api().get_symbol_count_page(state.session.sessionId, pageId);
      if (response?.status !== "success") {
        throw new Error(response?.message || "Could not render the drawing page.");
      }
      const image = await loadImage(response.data.imageDataUrl);
      if (token !== state.imageLoadToken) return;
      state.image = image;
      const canvas = byId("symbolCounterCanvas");
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const shell = byId("symbolCounterCanvasShell");
      if (shell) shell.hidden = false;
      const empty = byId("symbolCounterEmpty");
      if (empty) empty.hidden = true;
      drawCanvas();
      if (options.fit !== false) requestAnimationFrame(fitDrawing);
      setStatus("Drag a tight box around a complete symbol, or review the highlighted counts.");
    } catch (error) {
      setStatus(error?.message || "Failed to render the drawing.", true);
      notify(error?.message || "Failed to render the drawing.");
    } finally {
      if (token === state.imageLoadToken) setBusy(false);
    }
  }

  function pageTotal(pageId) {
    return state.symbols.reduce(
      (total, symbol) => total + symbol.matches.filter((match) => match.pageId === pageId).length,
      0
    );
  }

  function renderPages() {
    const container = byId("symbolCounterPages");
    const count = byId("symbolCounterPageCount");
    if (count) count.textContent = String(state.session?.pageCount || 0);
    if (!container) return;
    container.replaceChildren();
    if (!state.session?.documents?.length) {
      const empty = document.createElement("div");
      empty.className = "symbol-counter-side-empty";
      empty.textContent = "Load one or more PDF drawing sets to begin.";
      container.appendChild(empty);
      return;
    }

    state.session.documents.forEach((documentRecord) => {
      const group = document.createElement("div");
      group.className = "symbol-counter-document";
      const heading = document.createElement("div");
      heading.className = "symbol-counter-document-name";
      heading.textContent = documentRecord.name;
      heading.title = documentRecord.name;
      group.appendChild(heading);
      documentRecord.pageIds.forEach((pageId) => {
        const page = state.session.pages.find((item) => item.id === pageId);
        if (!page) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = `symbol-counter-page-btn${pageId === state.currentPageId ? " is-active" : ""}`;
        button.dataset.pageId = pageId;
        const number = document.createElement("span");
        number.className = "symbol-counter-page-number";
        number.textContent = String(page.pageIndex + 1).padStart(2, "0");
        const label = document.createElement("span");
        label.className = "symbol-counter-page-label";
        label.textContent = page.label;
        const total = document.createElement("span");
        total.className = "symbol-counter-page-total";
        const quantity = pageTotal(pageId);
        total.textContent = quantity ? String(quantity) : "";
        button.append(number, label, total);
        button.addEventListener("click", () => loadPage(pageId, { fit: true }));
        group.appendChild(button);
      });
      container.appendChild(group);
    });
  }

  function renderSymbols() {
    const container = byId("symbolCounterSymbols");
    if (!container) return;
    container.replaceChildren();
    if (!state.symbols.length) {
      const empty = document.createElement("div");
      empty.className = "symbol-counter-side-empty";
      empty.textContent = "Your symbol totals will appear here.";
      container.appendChild(empty);
      return;
    }
    state.symbols.forEach((symbol) => {
      const row = document.createElement("div");
      row.className = "symbol-counter-symbol-row";
      const button = document.createElement("button");
      button.type = "button";
      button.className = `symbol-counter-symbol-btn${symbol.id === state.activeSymbolId ? " is-active" : ""}`;
      const swatch = document.createElement("span");
      swatch.className = "symbol-counter-symbol-swatch";
      swatch.style.background = symbol.color;
      const copy = document.createElement("span");
      copy.className = "symbol-counter-symbol-copy";
      const name = document.createElement("span");
      name.className = "symbol-counter-symbol-name";
      name.textContent = symbol.name;
      const meta = document.createElement("span");
      meta.className = "symbol-counter-symbol-meta";
      const automatic = symbol.matches.filter((match) => !match.manual).length;
      const manual = symbol.matches.length - automatic;
      meta.textContent = manual ? `${automatic} auto + ${manual} manual` : `${automatic} automatic`;
      copy.append(name, meta);
      const total = document.createElement("strong");
      total.className = "symbol-counter-symbol-total";
      total.textContent = String(symbol.matches.length);
      button.append(swatch, copy, total);
      button.addEventListener("click", () => {
        state.activeSymbolId = symbol.id;
        state.selectedMatchId = "";
        state.mode = "select";
        renderAll();
        drawCanvas();
      });
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "symbol-counter-symbol-remove";
      removeButton.textContent = "×";
      removeButton.title = `Remove ${symbol.name} and all ${symbol.matches.length} counted instances`;
      removeButton.setAttribute("aria-label", removeButton.title);
      removeButton.addEventListener("click", () => removeSymbol(symbol.id));
      row.append(button, removeButton);
      container.appendChild(row);
    });
  }

  function renderSelectionControls() {
    const empty = byId("symbolCounterSelectionEmpty");
    const controls = byId("symbolCounterSelectionControls");
    const hasSelection = Boolean(state.selection && state.image);
    if (empty) empty.hidden = hasSelection;
    if (controls) controls.hidden = !hasSelection;
    if (!hasSelection) return;

    const name = byId("symbolCounterNameInput");
    if (name && !name.value.trim()) name.value = `Symbol ${state.symbols.length + 1}`;
    renderTemplatePreview();
  }

  function renderTemplatePreview() {
    const preview = byId("symbolCounterTemplatePreview");
    if (!preview || !state.selection || !state.image) return;
    const context = preview.getContext("2d");
    context.clearRect(0, 0, preview.width, preview.height);
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, preview.width, preview.height);
    const selection = state.selection;
    const sourceX = selection.x * state.image.naturalWidth;
    const sourceY = selection.y * state.image.naturalHeight;
    const sourceWidth = selection.width * state.image.naturalWidth;
    const sourceHeight = selection.height * state.image.naturalHeight;
    const scale = Math.min((preview.width - 18) / sourceWidth, (preview.height - 18) / sourceHeight, 4);
    const drawWidth = sourceWidth * scale;
    const drawHeight = sourceHeight * scale;
    context.imageSmoothingEnabled = true;
    context.drawImage(
      state.image,
      sourceX,
      sourceY,
      sourceWidth,
      sourceHeight,
      (preview.width - drawWidth) / 2,
      (preview.height - drawHeight) / 2,
      drawWidth,
      drawHeight
    );
  }

  function renderReviewControls() {
    const symbol = activeSymbol();
    const empty = byId("symbolCounterReviewEmpty");
    const controls = byId("symbolCounterReviewControls");
    if (empty) empty.hidden = Boolean(symbol);
    if (controls) controls.hidden = !symbol;
    if (!symbol) return;
    const total = byId("symbolCounterActiveTotal");
    if (total) total.textContent = String(symbol.matches.length);
    const deleteBtn = byId("symbolCounterDeleteMatchBtn");
    if (deleteBtn) deleteBtn.disabled = !state.selectedMatchId;
    const addBtn = byId("symbolCounterAddMissedBtn");
    if (addBtn) addBtn.textContent = state.mode === "add" ? "Cancel add" : "Add missed";
    const hint = byId("symbolCounterReviewHint");
    if (hint) {
      hint.classList.toggle("is-add-mode", state.mode === "add");
      hint.textContent =
        state.mode === "add"
          ? "Click the center of a missed symbol on the current drawing."
          : state.selectedMatchId
            ? "Selected marker ready to remove. Press Delete or use the button above."
            : "Click any marker to inspect it. Use Delete to remove a false positive.";
    }
    const viewport = byId("symbolCounterViewport");
    if (viewport) viewport.classList.toggle("is-add-mode", state.mode === "add");
    renderPageBreakdown(symbol);
  }

  function renderPageBreakdown(symbol) {
    const container = byId("symbolCounterPageBreakdown");
    if (!container) return;
    container.replaceChildren();
    if (!symbol) return;
    state.session?.pages?.forEach((page) => {
      const quantity = symbol.matches.filter((match) => match.pageId === page.id).length;
      if (!quantity) return;
      const row = document.createElement("div");
      row.className = "symbol-counter-breakdown-row";
      const label = document.createElement("span");
      label.textContent = `${page.documentName} · ${page.label}`;
      label.title = label.textContent;
      const total = document.createElement("strong");
      total.textContent = String(quantity);
      row.append(label, total);
      container.appendChild(row);
    });
  }

  function renderAll() {
    renderPages();
    renderSymbols();
    renderSelectionControls();
    renderReviewControls();
    const page = activePage();
    const title = byId("symbolCounterPageTitle");
    if (title) title.textContent = page ? `${page.documentName} · ${page.label}` : "No drawing loaded";
    const newBtn = byId("symbolCounterNewSymbolBtn");
    if (newBtn) newBtn.disabled = !state.session;
    const clearAllBtn = byId("symbolCounterClearAllBtn");
    if (clearAllBtn) clearAllBtn.disabled = !state.symbols.length || state.busy;
    const exportBtn = byId("symbolCounterExportBtn");
    if (exportBtn) exportBtn.disabled = !state.symbols.length || state.busy;
    const zoomDisabled = !state.image;
    ["symbolCounterZoomOutBtn", "symbolCounterZoomFitBtn", "symbolCounterZoomInBtn"].forEach((id) => {
      const element = byId(id);
      if (element) element.disabled = zoomDisabled;
    });
  }

  function rgba(hex, alpha) {
    const value = String(hex || "#10b981").replace("#", "");
    const normalized = value.length === 3 ? value.split("").map((char) => char + char).join("") : value;
    const number = Number.parseInt(normalized, 16);
    const red = (number >> 16) & 255;
    const green = (number >> 8) & 255;
    const blue = number & 255;
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  }

  function drawCanvas() {
    const canvas = byId("symbolCounterCanvas");
    if (!canvas || !state.image) return;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(state.image, 0, 0, canvas.width, canvas.height);

    state.symbols.forEach((symbol) => {
      const isActive = symbol.id === state.activeSymbolId;
      symbol.matches
        .filter((match) => match.pageId === state.currentPageId)
        .forEach((match, index) => {
          const x = match.x * canvas.width;
          const y = match.y * canvas.height;
          const width = match.width * canvas.width;
          const height = match.height * canvas.height;
          const isSelected = match.id === state.selectedMatchId;
          context.save();
          context.fillStyle = rgba(symbol.color, isActive ? 0.22 : 0.11);
          context.strokeStyle = symbol.color;
          context.lineWidth = isSelected ? 4 / state.zoom : isActive ? 2.4 / state.zoom : 1.5 / state.zoom;
          context.fillRect(x, y, width, height);
          context.strokeRect(x, y, width, height);
          const markerRadius = Math.max(7, Math.min(13, Math.min(width, height) * 0.23));
          context.beginPath();
          context.arc(x + width, y, markerRadius, 0, Math.PI * 2);
          context.fillStyle = symbol.color;
          context.fill();
          context.fillStyle = "#ffffff";
          context.font = `700 ${Math.max(8, markerRadius * 0.9)}px Inter, sans-serif`;
          context.textAlign = "center";
          context.textBaseline = "middle";
          context.fillText(String(index + 1), x + width, y + 0.5);
          context.restore();
        });
    });

    const selection = state.selectionDraft || state.selection;
    if (selection) {
      const x = selection.x * canvas.width;
      const y = selection.y * canvas.height;
      const width = selection.width * canvas.width;
      const height = selection.height * canvas.height;
      context.save();
      context.fillStyle = "rgba(16, 185, 129, 0.13)";
      context.strokeStyle = "#10b981";
      context.lineWidth = 2 / state.zoom;
      context.setLineDash([8 / state.zoom, 5 / state.zoom]);
      context.fillRect(x, y, width, height);
      context.strokeRect(x, y, width, height);
      context.restore();
    }
  }

  function setZoom(nextZoom, anchor = null) {
    if (!state.image) return;
    const viewport = byId("symbolCounterViewport");
    const canvas = byId("symbolCounterCanvas");
    if (!viewport || !canvas) return;
    const previousZoom = state.zoom || 1;
    const clamped = Math.max(0.08, Math.min(4, Number(nextZoom) || 1));
    const anchorX = anchor?.x ?? viewport.clientWidth / 2;
    const anchorY = anchor?.y ?? viewport.clientHeight / 2;
    const contentX = (viewport.scrollLeft + anchorX - 28) / previousZoom;
    const contentY = (viewport.scrollTop + anchorY - 28) / previousZoom;
    state.zoom = clamped;
    canvas.style.width = `${canvas.width * clamped}px`;
    canvas.style.height = `${canvas.height * clamped}px`;
    viewport.scrollLeft = contentX * clamped + 28 - anchorX;
    viewport.scrollTop = contentY * clamped + 28 - anchorY;
    const value = byId("symbolCounterZoomFitBtn");
    if (value) value.textContent = `${Math.round(clamped * 100)}%`;
    drawCanvas();
  }

  function fitDrawing() {
    if (!state.image) return;
    const viewport = byId("symbolCounterViewport");
    if (!viewport) return;
    const availableWidth = Math.max(100, viewport.clientWidth - 56);
    const availableHeight = Math.max(100, viewport.clientHeight - 56);
    const fit = Math.min(
      availableWidth / state.image.naturalWidth,
      availableHeight / state.image.naturalHeight
    );
    setZoom(fit);
    viewport.scrollLeft = 0;
    viewport.scrollTop = 0;
  }

  function canvasPoint(event) {
    const canvas = byId("symbolCounterCanvas");
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(canvas.width, ((event.clientX - rect.left) / rect.width) * canvas.width)),
      y: Math.max(0, Math.min(canvas.height, ((event.clientY - rect.top) / rect.height) * canvas.height)),
    };
  }

  function normalizedFromPoints(start, end) {
    const canvas = byId("symbolCounterCanvas");
    const left = Math.min(start.x, end.x);
    const top = Math.min(start.y, end.y);
    const right = Math.max(start.x, end.x);
    const bottom = Math.max(start.y, end.y);
    return {
      x: left / canvas.width,
      y: top / canvas.height,
      width: (right - left) / canvas.width,
      height: (bottom - top) / canvas.height,
    };
  }

  function hitMatch(point) {
    const canvas = byId("symbolCounterCanvas");
    const orderedSymbols = [...state.symbols].sort((a, b) => {
      if (a.id === state.activeSymbolId) return 1;
      if (b.id === state.activeSymbolId) return -1;
      return 0;
    });
    for (let symbolIndex = orderedSymbols.length - 1; symbolIndex >= 0; symbolIndex -= 1) {
      const symbol = orderedSymbols[symbolIndex];
      const matches = symbol.matches.filter((match) => match.pageId === state.currentPageId);
      for (let index = matches.length - 1; index >= 0; index -= 1) {
        const match = matches[index];
        const left = match.x * canvas.width;
        const top = match.y * canvas.height;
        const right = left + match.width * canvas.width;
        const bottom = top + match.height * canvas.height;
        if (point.x >= left && point.x <= right && point.y >= top && point.y <= bottom) {
          return { symbol, match };
        }
      }
    }
    return null;
  }

  function addManualMatch(point) {
    const symbol = activeSymbol();
    const canvas = byId("symbolCounterCanvas");
    if (!symbol || !canvas) return;
    const pixelWidth = Number(symbol.templateRect?.pixelWidth) || Math.max(12, symbol.templateRect.width * canvas.width);
    const pixelHeight = Number(symbol.templateRect?.pixelHeight) || Math.max(12, symbol.templateRect.height * canvas.height);
    const width = Math.min(1, pixelWidth / canvas.width);
    const height = Math.min(1, pixelHeight / canvas.height);
    symbol.matches.push({
      id: `manual-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      pageId: state.currentPageId,
      x: Math.max(0, Math.min(1 - width, point.x / canvas.width - width / 2)),
      y: Math.max(0, Math.min(1 - height, point.y / canvas.height - height / 2)),
      width,
      height,
      score: 1,
      rotation: 0,
      scale: 1,
      manual: true,
    });
    state.mode = "select";
    state.selectedMatchId = symbol.matches[symbol.matches.length - 1].id;
    setStatus(`Manual ${symbol.name} marker added.`);
    renderAll();
    drawCanvas();
  }

  function onCanvasPointerDown(event) {
    if (!state.image || state.busy) return;
    const canvas = byId("symbolCounterCanvas");
    const viewport = byId("symbolCounterViewport");
    if (event.button === 1 || state.spaceDown) {
      event.preventDefault();
      state.interaction = {
        type: "pan",
        startX: event.clientX,
        startY: event.clientY,
        scrollLeft: viewport.scrollLeft,
        scrollTop: viewport.scrollTop,
      };
      viewport.classList.add("is-panning");
      canvas.setPointerCapture(event.pointerId);
      return;
    }
    if (event.button !== 0) return;
    const point = canvasPoint(event);
    if (state.mode === "add") {
      addManualMatch(point);
      return;
    }
    const hit = hitMatch(point);
    if (hit) {
      state.activeSymbolId = hit.symbol.id;
      state.selectedMatchId = hit.match.id;
      state.selection = null;
      state.selectionDraft = null;
      renderAll();
      drawCanvas();
      return;
    }
    state.activeSymbolId = "";
    state.selectedMatchId = "";
    state.selection = null;
    state.interaction = { type: "select", start: point, current: point };
    state.selectionDraft = normalizedFromPoints(point, point);
    canvas.setPointerCapture(event.pointerId);
    renderAll();
    drawCanvas();
  }

  function onCanvasPointerMove(event) {
    const interaction = state.interaction;
    if (!interaction) return;
    const viewport = byId("symbolCounterViewport");
    if (interaction.type === "pan") {
      viewport.scrollLeft = interaction.scrollLeft - (event.clientX - interaction.startX);
      viewport.scrollTop = interaction.scrollTop - (event.clientY - interaction.startY);
      return;
    }
    if (interaction.type === "select") {
      interaction.current = canvasPoint(event);
      state.selectionDraft = normalizedFromPoints(interaction.start, interaction.current);
      drawCanvas();
    }
  }

  function onCanvasPointerUp(event) {
    const interaction = state.interaction;
    if (!interaction) return;
    state.interaction = null;
    byId("symbolCounterViewport")?.classList.remove("is-panning");
    try {
      byId("symbolCounterCanvas")?.releasePointerCapture(event.pointerId);
    } catch (_) {
      // Pointer capture may already have been released by the browser.
    }
    if (interaction.type !== "select") return;
    const selection = normalizedFromPoints(interaction.start, interaction.current);
    const canvas = byId("symbolCounterCanvas");
    const pixelWidth = selection.width * canvas.width;
    const pixelHeight = selection.height * canvas.height;
    state.selectionDraft = null;
    if (pixelWidth < 8 || pixelHeight < 8) {
      state.selection = null;
      setStatus("Draw a larger box around the complete symbol.", true);
    } else {
      state.selection = selection;
      const nameInput = byId("symbolCounterNameInput");
      if (nameInput) nameInput.value = `Symbol ${state.symbols.length + 1}`;
      setStatus("Selection ready. Name the symbol and choose Find matches.");
    }
    renderAll();
    drawCanvas();
  }

  async function runCount() {
    if (!state.session || !state.selection || !state.currentPageId || state.busy) return;
    const nameInput = byId("symbolCounterNameInput");
    const name = String(nameInput?.value || "").trim();
    if (!name) {
      nameInput?.focus();
      setStatus("Enter a name for this symbol.", true);
      return;
    }
    const threshold = Number(byId("symbolCounterThresholdInput")?.value || 82) / 100;
    const scope = byId("symbolCounterScopeInput")?.value || "all";
    const pageCount = scope === "current" ? 1 : state.session.pageCount;
    setBusy(
      true,
      `Finding ${name}…`,
      `Comparing the selection across ${pageCount} page${pageCount === 1 ? "" : "s"}.`
    );
    setStatus(`Searching ${pageCount} page${pageCount === 1 ? "" : "s"} for ${name}…`);
    try {
      const response = await api().count_pdf_symbols(state.session.sessionId, {
        sourcePageId: state.currentPageId,
        selection: state.selection,
        threshold,
        scope,
        rotations: byId("symbolCounterRotationsInput")?.checked === true,
        scaleTolerance: byId("symbolCounterScaleInput")?.checked === true,
      });
      if (response?.status !== "success") {
        throw new Error(response?.message || "Symbol matching failed.");
      }
      const data = response.data;
      const symbol = {
        id: `symbol-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
        name,
        color: COLORS[state.symbols.length % COLORS.length],
        templatePageId: state.currentPageId,
        templateRect: data.templateRect,
        threshold: data.threshold,
        matches: Array.isArray(data.matches) ? data.matches : [],
      };
      state.symbols.push(symbol);
      state.activeSymbolId = symbol.id;
      state.selectedMatchId = "";
      state.selection = null;
      state.selectionDraft = null;
      state.mode = "select";
      if (nameInput) nameInput.value = "";
      setStatus(`Found ${symbol.matches.length} ${name}${symbol.matches.length === 1 ? "" : "s"}. Review the highlighted markers.`);
      renderAll();
      drawCanvas();
    } catch (error) {
      setStatus(error?.message || "Symbol matching failed.", true);
      notify(error?.message || "Symbol matching failed.");
    } finally {
      setBusy(false);
      renderAll();
    }
  }

  function newSymbol() {
    if (!state.session) return;
    state.activeSymbolId = "";
    state.selectedMatchId = "";
    state.selection = null;
    state.selectionDraft = null;
    state.mode = "select";
    const name = byId("symbolCounterNameInput");
    if (name) name.value = "";
    setStatus("Drag a tight box around another symbol.");
    renderAll();
    drawCanvas();
  }

  function toggleAddMode() {
    if (!activeSymbol()) return;
    state.mode = state.mode === "add" ? "select" : "add";
    state.selectedMatchId = "";
    renderReviewControls();
    drawCanvas();
  }

  function deleteSelectedMatch() {
    if (!state.selectedMatchId) return;
    const symbol = activeSymbol();
    if (!symbol) return;
    const index = symbol.matches.findIndex((match) => match.id === state.selectedMatchId);
    if (index < 0) return;
    symbol.matches.splice(index, 1);
    state.selectedMatchId = "";
    setStatus(`Removed one ${symbol.name} marker.`);
    renderAll();
    drawCanvas();
  }

  function removeSymbol(symbolId) {
    if (state.busy) return;
    const index = state.symbols.findIndex((symbol) => symbol.id === symbolId);
    if (index < 0) return;
    const [removed] = state.symbols.splice(index, 1);
    if (state.activeSymbolId === symbolId) {
      const nextSymbol = state.symbols[index] || state.symbols[index - 1] || null;
      state.activeSymbolId = nextSymbol?.id || "";
    }
    state.selectedMatchId = "";
    state.mode = "select";
    setStatus(`Removed ${removed.name} and all ${removed.matches.length} counted instance${removed.matches.length === 1 ? "" : "s"}.`);
    renderAll();
    drawCanvas();
  }

  function clearAllCounts() {
    if (state.busy || !state.symbols.length) return;
    const symbolTypes = state.symbols.length;
    const markerCount = state.symbols.reduce((total, symbol) => total + symbol.matches.length, 0);
    const message = markerCount
      ? `Delete all ${markerCount} counted marker${markerCount === 1 ? "" : "s"} across ${symbolTypes} symbol type${symbolTypes === 1 ? "" : "s"}? This cannot be undone.`
      : `Delete all ${symbolTypes} counted symbol type${symbolTypes === 1 ? "" : "s"}? This cannot be undone.`;
    if (!window.confirm(message)) return;

    state.symbols = [];
    state.activeSymbolId = "";
    state.selectedMatchId = "";
    state.selection = null;
    state.selectionDraft = null;
    state.mode = "select";
    const nameInput = byId("symbolCounterNameInput");
    if (nameInput) nameInput.value = "";
    setStatus(`Deleted all ${markerCount} counted symbol${markerCount === 1 ? "" : "s"}. Drag around a symbol to start again.`);
    renderAll();
    drawCanvas();
  }

  async function exportResults() {
    if (!state.session || !state.symbols.length || state.busy) return;
    if (!api()?.export_symbol_count_results) {
      notify("Excel export is available in the desktop app.");
      return;
    }
    setBusy(true, "Preparing Excel takeoff…", "Building summary, page counts, and an audit trail.");
    try {
      const payload = state.symbols.map((symbol) => ({
        name: symbol.name,
        color: symbol.color,
        matches: symbol.matches,
      }));
      const response = await api().export_symbol_count_results(state.session.sessionId, payload);
      if (response?.status === "cancelled") return;
      if (response?.status !== "success") {
        throw new Error(response?.message || "Excel export failed.");
      }
      const result = response.data;
      setStatus(`Exported ${result.instanceCount} counted symbols to Excel.`);
      notify(`Symbol count exported: ${result.path}`, 6500);
    } catch (error) {
      setStatus(error?.message || "Excel export failed.", true);
      notify(error?.message || "Excel export failed.");
    } finally {
      setBusy(false);
      renderAll();
    }
  }

  function onViewportWheel(event) {
    if (!state.image || state.busy) return;
    event.preventDefault();
    const viewport = byId("symbolCounterViewport");
    const rect = viewport.getBoundingClientRect();
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    setZoom(state.zoom * factor, {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    });
  }

  function isDialogOpen() {
    return byId("symbolCounterDlg")?.open === true;
  }

  function onKeyDown(event) {
    if (!isDialogOpen()) return;
    const editing = /INPUT|TEXTAREA|SELECT/.test(event.target?.tagName || "");
    if (event.code === "Space" && !editing) {
      state.spaceDown = true;
      event.preventDefault();
    }
    if ((event.key === "Delete" || event.key === "Backspace") && !editing && state.selectedMatchId) {
      event.preventDefault();
      deleteSelectedMatch();
    }
    if (event.key === "Escape" && state.mode === "add") {
      event.preventDefault();
      state.mode = "select";
      renderReviewControls();
    }
  }

  function onKeyUp(event) {
    if (event.code === "Space") state.spaceDown = false;
  }

  function bindEvents() {
    const card = byId("toolSymbolCounter");
    if (card) {
      const openHandler = (event) => {
        if (!guardUnderConstructionToolAccess(card, "Symbol Counter", event)) return;
        openSymbolCounter();
      };
      card.addEventListener("click", openHandler);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openHandler(event);
        }
      });
    }
    byId("symbolCounterCloseBtn")?.addEventListener("click", closeSymbolCounter);
    byId("symbolCounterLoadBtn")?.addEventListener("click", loadDocuments);
    byId("symbolCounterEmptyLoadBtn")?.addEventListener("click", loadDocuments);
    byId("symbolCounterExportBtn")?.addEventListener("click", exportResults);
    byId("symbolCounterNewSymbolBtn")?.addEventListener("click", newSymbol);
    byId("symbolCounterClearAllBtn")?.addEventListener("click", clearAllCounts);
    byId("symbolCounterRunBtn")?.addEventListener("click", runCount);
    byId("symbolCounterAddMissedBtn")?.addEventListener("click", toggleAddMode);
    byId("symbolCounterDeleteMatchBtn")?.addEventListener("click", deleteSelectedMatch);
    byId("symbolCounterZoomOutBtn")?.addEventListener("click", () => setZoom(state.zoom / 1.18));
    byId("symbolCounterZoomInBtn")?.addEventListener("click", () => setZoom(state.zoom * 1.18));
    byId("symbolCounterZoomFitBtn")?.addEventListener("click", fitDrawing);

    const threshold = byId("symbolCounterThresholdInput");
    threshold?.addEventListener("input", () => {
      const value = byId("symbolCounterThresholdValue");
      if (value) value.textContent = `${threshold.value}%`;
    });

    const canvas = byId("symbolCounterCanvas");
    canvas?.addEventListener("pointerdown", onCanvasPointerDown);
    canvas?.addEventListener("pointermove", onCanvasPointerMove);
    canvas?.addEventListener("pointerup", onCanvasPointerUp);
    canvas?.addEventListener("pointercancel", onCanvasPointerUp);
    canvas?.addEventListener("contextmenu", (event) => event.preventDefault());
    byId("symbolCounterViewport")?.addEventListener("wheel", onViewportWheel, { passive: false });
    byId("symbolCounterDlg")?.addEventListener("close", () => {
      state.spaceDown = false;
      state.mode = "select";
      state.interaction = null;
    });
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("keyup", onKeyUp, true);
    window.addEventListener("resize", () => {
      if (isDialogOpen() && state.image) requestAnimationFrame(fitDrawing);
    });
  }

  function initialize() {
    bindEvents();
    renderAll();
    window.openSymbolCounter = openSymbolCounter;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
