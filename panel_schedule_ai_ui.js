(() => {
  "use strict";

  // Panel Schedule AI Studio powered by Gemini 4 Hydrogen (free tier).
  // Two structured intake workflows:
  //   1. Site Survey Photos: Multi-panel tabs, each with 4 dedicated photo buckets
  //      (Panelboard Tags/Nameplate, Circuit Breakers, Printed/Door Circuit Directory,
  //      Main Breaker/Main Lugs) guaranteed to merge into 1 panel per tab.
  //   2. As-Built / Record Drawings: Multi-page PDFs or printed schedule images
  //      that auto-extract 1 or many panels per sheet with exact visible kVA.

  const LOAD_CODES = ["", "C", "D", "G", "K", "M", "ML"];
  const FIELD_BUCKETS = ["nameplate", "breakers", "directory", "main_breaker", "full_panel"];
  const ROLE_SHORT_LABELS = {
    nameplate: "Tag/Label",
    breakers: "Breakers",
    directory: "Directory",
    main_breaker: "Main",
    full_panel: "Full Panel",
    as_built_drawing: "Drawing",
    auto: "Source",
  };

  const BUCKET_MOVE_OPTIONS = [
    { value: "nameplate", label: "1. Tag / Nameplate" },
    { value: "breakers", label: "2. Breakers" },
    { value: "directory", label: "3. Directory" },
    { value: "main_breaker", label: "4. Main Breaker" },
    { value: "full_panel", label: "5. Full Panel" },
    { value: "ignore", label: "Ignore (skip)" },
  ];

  function createFieldGroup(index = 1) {
    return {
      id: `grp_${Math.random().toString(36).slice(2, 10)}`,
      panelName: "",
      defaultLabel: `Panel ${index}`,
      condition: "EXISTING",
      buckets: {
        nameplate: [],
        breakers: [],
        directory: [],
        main_breaker: [],
        full_panel: [],
      },
      ignored: [],
    };
  }

  const initialGroup = createFieldGroup(1);

  const state = {
    step: "sources", // "sources" | "review"
    workflow: "field_photos", // "field_photos" | "as_built_drawing"
    // Workflow A: Structured Site Survey Photos (multi-panel groups)
    fieldGroups: [initialGroup],
    activeFieldGroupId: initialGroup.id,
    activePasteBucket: "breakers",
    pendingBrowseTarget: null, // { workflow, bucket }
    // Workflow B: As-Built / Record Drawings
    drawingSources: [],
    drawingPanelNameHint: "",
    // Source lookup table by id (for Step 2 viewer)
    sourceById: new Map(),
    // Step 2: Review & Export
    panels: [],
    activePanelId: "",
    activeSourceIndex: 0,
    flagCursor: -1,
    busy: false,
    modelName: "gemini-4-hydrogen",
    hasApiKey: true,
    launchContext: null,
    // Viewer transform state
    zoom: 1,
    panX: 0,
    panY: 0,
    rotation: 0,
    dragging: false,
    dragStartX: 0,
    dragStartY: 0,
    // Drag-and-drop internal photo move state
    draggedPhoto: null, // { groupId, fromBucket, index, itemId }
    // Fullscreen Lightbox & Cropper state
    lightbox: {
      open: false,
      source: null,
      context: null, // { workflow: "field_photos", groupId, bucket, index } | { workflow: "as_built_drawing", index }
      zoom: 1,
      panX: 0,
      panY: 0,
      rotation: 0,
      dragging: false,
      dragStartX: 0,
      dragStartY: 0,
      cropMode: false,
      cropping: false,
      cropStart: null, // { x, y } in [0..1]
      cropRect: null, // { x, y, w, h } in [0..1]
    },
    // Non-blocking background extraction job state
    bgJob: {
      running: false,
      jobId: "",
      activityId: "",
      progress: 0,
      message: "",
      startedAt: 0,
      pollTimer: 0,
      tickTimer: 0,
    },
    duplicateIds: new Set(),
    // Export state
    exportMode: "new", // "new" | "existing"
    exportFormat: "xlsx", // "xlsx" | "xls"
    exportPath: "",
    replaceExistingSheets: false,
    lastExportedPath: "",
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
    console.info(`[panel-studio] ${message}`);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function setStatus(message, kind = "") {
    const node = byId("psaFooterStatus");
    if (!node) return;
    const text = String(message || "");
    node.textContent = text;
    node.title = text;
    node.classList.toggle("is-error", kind === "error");
    node.classList.toggle("is-success", kind === "success");
  }

  function setBusy(isBusy, title = "Working...", sub = "") {
    state.busy = Boolean(isBusy);
    const overlay = byId("psaBusyOverlay");
    if (overlay) overlay.hidden = !state.busy;
    const t = byId("psaBusyTitle");
    if (t) t.textContent = title;
    const s = byId("psaBusySub");
    if (s) s.textContent = sub;
    renderFooterControls();
  }

  function getActiveFieldGroup() {
    return (
      state.fieldGroups.find((g) => g.id === state.activeFieldGroupId) ||
      state.fieldGroups[0] ||
      null
    );
  }

  function getGroupSources(group) {
    if (!group) return [];
    const list = [];
    for (const bucket of FIELD_BUCKETS) {
      for (const item of group.buckets[bucket] || []) {
        list.push(item);
      }
    }
    return list;
  }

  function getReadyFieldGroups() {
    return state.fieldGroups.filter((g) => getGroupSources(g).length > 0);
  }

  function getSelectedDrawingSources() {
    return state.drawingSources.filter((s) => s.selected !== false);
  }

  function getActivePanel() {
    return state.panels.find((p) => p.id === state.activePanelId) || state.panels[0] || null;
  }

  function getViewerSourcesForActivePanel() {
    const panel = getActivePanel();
    if (panel?.sourceIds?.length) {
      const matched = panel.sourceIds
        .map((id) => state.sourceById.get(id))
        .filter(Boolean);
      if (matched.length) return matched;
    }
    // Fallback to all loaded sources
    const fallback = [];
    for (const grp of state.fieldGroups) {
      fallback.push(...getGroupSources(grp));
    }
    fallback.push(...getSelectedDrawingSources());
    return fallback;
  }

  function getDefaultDirectory() {
    const ctx = state.launchContext;
    if (!ctx) return null;
    return ctx.electricalDir || ctx.projectPath || ctx.path || null;
  }

  function registerSourcesInIndex(items) {
    for (const item of items || []) {
      if (item?.id) {
        state.sourceById.set(item.id, item);
      }
    }
  }

  // ------------------------------------------------------------------
  // NEC Connected & Demand Load Calculation (matches Template.xlsx)
  // ------------------------------------------------------------------

  function parseNum(val) {
    if (val === "" || val === null || val === undefined) return null;
    const n = Number(val);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }

  function isSpareOrSpace(desc) {
    const u = String(desc || "").trim().toUpperCase();
    return (
      u === "SPARE" ||
      u.startsWith("SPARE ") ||
      u.includes(" SPARE") ||
      u === "SPACE" ||
      u.startsWith("SPACE ") ||
      u === "UNUSED" ||
      u === "BLANK"
    );
  }

  function ampsDivisor(voltage, phase) {
    const v = String(voltage || "").toUpperCase();
    const p = Number(phase) === 1 ? 1 : 3;
    if (p === 1) {
      if (v.includes("208")) return 0.208;
      if (v.includes("277")) return 0.277;
      if (v.includes("480")) return 0.48;
      return 0.24;
    }
    if (v.includes("480") || v.includes("277")) return 0.831;
    if (v.includes("240") && !v.includes("208")) return 0.416;
    return 0.36;
  }

  function computePanelSummary(panel) {
    const phaseTotals = { A: 0, B: 0, C: 0 };
    const cats = { C: 0, D: 0, G: 0, K: 0, M: 0, ML: 0 };
    let kitchenCount = 0;
    let flaggedCount = 0;
    let missingKvaCount = 0;

    for (const ckt of panel.circuits || []) {
      const cNum = Number(ckt.circuitNumber);
      if (!Number.isInteger(cNum) || cNum < 1) continue;
      if (ckt.confidence === "medium" || ckt.confidence === "low") flaggedCount += 1;
      const desc = String(ckt.description || "").trim();
      const poles = Number(ckt.poles) || 0;
      const lType = String(ckt.loadType || "").trim().toUpperCase();
      const pk = Array.isArray(ckt.phaseKva) ? ckt.phaseKva : [];

      if (desc && !isSpareOrSpace(desc) && poles > 0) {
        const hasVal = pk.some((v) => parseNum(v) !== null);
        if (!hasVal) missingKvaCount += 1;
      }

      const span = poles > 0 ? poles : 0;
      for (let i = 0; i < span; i++) {
        const rowCkt = cNum + i * 2;
        const rowZero = Math.floor((rowCkt - 1) / 2);
        const ph = ["A", "B", "C"][rowZero % 3];
        const v = parseNum(pk[i]);
        if (v !== null) {
          phaseTotals[ph] += v;
          if (lType in cats) cats[lType] += v;
        }
        if (lType === "K") kitchenCount += 1;
      }
    }

    const connectedTotal = phaseTotals.A + phaseTotals.B + phaseTotals.C;
    const demandC = cats.C * 1.25;
    const demandD = cats.D;
    const demandG = cats.G > 10 ? 10 + (cats.G - 10) * 0.5 : cats.G;
    const kFactors = [1, 1, 0.9, 0.8, 0.7, 0.65];
    const demandK = kitchenCount > 0 ? cats.K * kFactors[Math.min(6, Math.max(1, kitchenCount)) - 1] : 0;
    const demandM = cats.M;
    const demandML = cats.ML * 1.25;
    const demandTotal = demandC + demandD + demandG + demandK + demandM + demandML;
    const phaseInt = Number(panel.phase) === 1 ? 1 : 3;
    const div = ampsDivisor(panel.voltage, phaseInt);
    const demandAmps = div > 0 ? demandTotal / div : 0;

    const activePhases =
      phaseInt === 1 ? [phaseTotals.A, phaseTotals.B] : [phaseTotals.A, phaseTotals.B, phaseTotals.C];
    const maxP = Math.max(...activePhases, 0);
    const minP = Math.min(...activePhases, 0);
    const imbalancePct = maxP > 0 ? ((maxP - minP) / maxP) * 100 : 0;

    return {
      phaseA: Number(phaseTotals.A.toFixed(2)),
      phaseB: Number(phaseTotals.B.toFixed(2)),
      phaseC: Number(phaseTotals.C.toFixed(2)),
      connectedTotalKva: Number(connectedTotal.toFixed(2)),
      demandTotalKva: Number(demandTotal.toFixed(2)),
      demandAmps: Number(demandAmps.toFixed(1)),
      imbalancePct: Number(imbalancePct.toFixed(1)),
      flaggedCount,
      missingKvaCount,
    };
  }

  function buildSlotMap(panel) {
    const map = new Map();
    const circuits = [...(panel.circuits || [])].sort((a, b) => Number(a.circuitNumber) - Number(b.circuitNumber));
    for (const ckt of circuits) {
      const cNum = Number(ckt.circuitNumber);
      if (!Number.isInteger(cNum) || cNum < 1) continue;
      if (map.has(cNum)) continue;
      map.set(cNum, { kind: "head", circuit: ckt, offset: 0 });
      const poles = Number(ckt.poles) || 0;
      if (poles > 1) {
        for (let offset = 1; offset < poles; offset++) {
          const childNum = cNum + offset * 2;
          map.set(childNum, { kind: "continuation", circuit: ckt, offset });
        }
      }
    }
    return map;
  }

  function ensureCircuitAt(panel, cktNum) {
    let existing = (panel.circuits || []).find((c) => Number(c.circuitNumber) === cktNum);
    if (!existing) {
      existing = {
        circuitNumber: cktNum,
        description: "",
        breakerAmps: "",
        poles: 1,
        loadType: "",
        note: "1",
        phaseKva: [null],
        kvaEstimated: false,
        confidence: "high",
        reviewNote: "",
      };
      panel.circuits.push(existing);
    }
    return existing;
  }

  function createBlankPanel(name = "A") {
    return {
      id: `pnl_${Math.random().toString(36).slice(2, 10)}`,
      includeInExport: true,
      panelName: name,
      sourceKind: "manual",
      sourceIndices: [0],
      sourceIds: [],
      voltage: "120/208V",
      busRating: "225A",
      mainType: "MLO",
      mainBreakerAmps: "",
      mainRequirement: "MLO",
      phase: 3,
      wire: 4,
      mounting: "SURFACE",
      enclosure: "NEMA 1",
      aicRating: "EXISTING",
      condition: "EXISTING",
      fedFrom: "",
      circuitCount: 42,
      headerWarnings: [],
      notes: "",
      circuits: [],
    };
  }

  // ------------------------------------------------------------------
  // Source Ingestion (Bucketed Field Photos + Record Drawing PDFs)
  // ------------------------------------------------------------------

  function fileToUploadPayload(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve({ name: file.name || "pasted_image.png", dataUrl: reader.result });
      reader.onerror = () => reject(new Error(`Could not read ${file.name || "file"}`));
      reader.readAsDataURL(file);
    });
  }

  function attachInspectedItems(items, targetWorkflow, targetBucket = null) {
    registerSourcesInIndex(items);
    if (targetWorkflow === "field_photos") {
      const group = getActiveFieldGroup();
      if (!group) return;
      const bucket = FIELD_BUCKETS.includes(targetBucket) ? targetBucket : state.activePasteBucket;
      for (const item of items) {
        item.role = bucket;
        item.selected = true;
        group.buckets[bucket].push(item);
      }
    } else {
      for (const item of items) {
        item.role = "as_built_drawing";
        state.drawingSources.push(item);
      }
    }
  }

  async function addPathsToTarget(paths, targetWorkflow, targetBucket = null) {
    if (!paths || !paths.length) return;
    const bridge = api();
    if (!bridge?.panel_studio_inspect_sources) {
      notify("Panel Schedule Studio backend is not ready.");
      return;
    }
    setBusy(true, "Loading source files...", "Generating thumbnails and inspecting pages...");
    try {
      const res = await bridge.panel_studio_inspect_sources(paths, []);
      if (res?.status !== "success") {
        throw new Error(res?.message || "Failed to load selected files.");
      }
      const added = res.items || [];
      attachInspectedItems(added, targetWorkflow, targetBucket);
      if (res.warnings?.length) notify(res.warnings[0], 5000);
      setStatus(`Added ${added.length} item(s).`, "success");
      renderAll();
    } catch (err) {
      setStatus(err?.message || "Could not inspect source files.", "error");
      notify(err?.message || "Could not inspect source files.");
    } finally {
      setBusy(false);
    }
  }

  async function addBrowserFilesToTarget(fileList, targetWorkflow, targetBucket = null) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const bridge = api();
    if (!bridge?.panel_studio_inspect_sources) {
      notify("Panel Schedule Studio backend is not ready.");
      return;
    }
    setBusy(true, "Loading files...", "Preparing images and PDF pages...");
    try {
      const uploads = [];
      for (const file of files) {
        uploads.push(await fileToUploadPayload(file));
      }
      const res = await bridge.panel_studio_inspect_sources([], uploads);
      if (res?.status !== "success") {
        throw new Error(res?.message || "Failed to load uploaded files.");
      }
      const added = res.items || [];
      attachInspectedItems(added, targetWorkflow, targetBucket);
      if (res.warnings?.length) notify(res.warnings[0], 5000);
      setStatus(`Added ${added.length} item(s).`, "success");
      renderAll();
    } catch (err) {
      setStatus(err?.message || "Could not load files.", "error");
      notify(err?.message || "Could not load files.");
    } finally {
      setBusy(false);
    }
  }

  async function browseForTarget(targetWorkflow, targetBucket = null) {
    if (targetWorkflow === "field_photos" && targetBucket) {
      setActivePasteBucket(targetBucket);
    }
    const bridge = api();
    if (bridge?.select_files) {
      const fileTypes =
        targetWorkflow === "field_photos"
          ? [
              "Panel Photos (*.jpg;*.jpeg;*.png;*.heic;*.heif;*.tif;*.tiff;*.bmp;*.webp;*.pdf)",
              "Image Files (*.jpg;*.jpeg;*.png;*.heic;*.heif;*.tif;*.tiff;*.bmp;*.webp)",
              "PDF Files (*.pdf)",
            ]
          : [
              "Drawings & PDFs (*.pdf;*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp;*.webp)",
              "PDF Drawings (*.pdf)",
              "Image Files (*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp;*.webp)",
            ];
      const res = await bridge.select_files({
        allow_multiple: true,
        default_directory: getDefaultDirectory(),
        file_types: fileTypes,
      });
      if (res?.status === "success" && res.paths?.length) {
        await addPathsToTarget(res.paths, targetWorkflow, targetBucket);
      }
      return;
    }
    state.pendingBrowseTarget = { workflow: targetWorkflow, bucket: targetBucket };
    const input = byId("psaFallbackFileInput");
    if (input) {
      input.value = "";
      input.click();
    }
  }

  // ------------------------------------------------------------------
  // Fast Photo Auto-Sorting with gemini-decision-1
  // ------------------------------------------------------------------

  async function autoSortInspectedItems(items) {
    if (!items || !items.length) return;
    registerSourcesInIndex(items);
    const bridge = api();
    if (!bridge?.panel_studio_auto_sort_photos) {
      notify("Auto-sort backend is not ready.");
      return;
    }
    const splitPanels = Boolean(byId("psaAutoSortSplitCb")?.checked);
    setBusy(
      true,
      "Auto-sorting photos with gemini-decision-1...",
      `Classifying ${items.length} photo(s) into Nameplate, Breakers, Directory, Main Breaker, and Ignored...`
    );
    try {
      const leanSources = items.map((s) => ({
        id: s.id,
        kind: s.kind,
        name: s.name,
        path: s.path,
        pageIndex: s.pageIndex,
        pageLabel: s.pageLabel,
      }));
      const res = await bridge.panel_studio_auto_sort_photos({
        sources: leanSources,
        splitPanels,
      });
      if (res?.status !== "success") {
        throw new Error(res?.message || "Auto-sort failed.");
      }

      const assignments = res.assignments || [];
      const itemMap = new Map(items.map((it) => [it.id, it]));
      const activeGroup = getActiveFieldGroup();
      const groupTargets = new Map();

      if (splitPanels) {
        const panelCount = Math.max(1, Number(res.panelGroupCount) || 1);
        const reuseActive = activeGroup && getGroupSources(activeGroup).length === 0 && !(activeGroup.ignored?.length);
        for (let gIdx = 0; gIdx < panelCount; gIdx++) {
          if (gIdx === 0 && reuseActive) {
            groupTargets.set(0, activeGroup);
          } else {
            const grp = createFieldGroup(state.fieldGroups.length + 1);
            state.fieldGroups.push(grp);
            groupTargets.set(gIdx, grp);
          }
        }
        state.activeFieldGroupId = groupTargets.get(0)?.id || state.activeFieldGroupId;
      } else {
        groupTargets.set(0, activeGroup);
      }

      let ignoredCount = 0;
      let lowConfCount = 0;
      for (const assign of assignments) {
        const item = itemMap.get(assign.id);
        if (!item) continue;
        const targetGroup = groupTargets.get(assign.panelGroupIndex || 0) || activeGroup;
        if (!targetGroup) continue;
        const bucket = assign.bucket || "breakers";
        item.sortConfidence = assign.confidence;
        item.sortLowConfidence = Boolean(assign.lowConfidence);
        if (assign.lowConfidence) lowConfCount += 1;
        if (assign.suggestedHint && !item.hint) {
          item.hint = assign.suggestedHint;
        }
        if (bucket === "ignore") {
          item.role = "ignore";
          targetGroup.ignored.push(item);
          ignoredCount += 1;
        } else {
          const destBucket = FIELD_BUCKETS.includes(bucket) ? bucket : "breakers";
          item.role = destBucket;
          item.selected = true;
          targetGroup.buckets[destBucket].push(item);
        }
      }

      const elapsed = res.elapsedMs ? ` in ${(res.elapsedMs / 1000).toFixed(2)}s` : "";
      const splitNote = splitPanels ? ` across ${groupTargets.size} panel tab(s)` : "";
      const ignNote = ignoredCount ? `, ${ignoredCount} ignored` : "";
      const lowNote = lowConfCount ? `, ${lowConfCount} low-confidence (highlighted)` : "";
      setStatus(
        `Sorted ${assignments.length} photo(s) with gemini-decision-1${elapsed}${splitNote}${ignNote}${lowNote}.`,
        "success"
      );
      renderAll();
    } catch (err) {
      setStatus(err?.message || "Auto-sort failed.", "error");
      notify(err?.message || "Auto-sort failed.", 6000);
    } finally {
      setBusy(false);
    }
  }

  async function autoSortPaths(paths) {
    if (!paths || !paths.length) return;
    const bridge = api();
    if (!bridge?.panel_studio_inspect_sources) return;
    setBusy(true, "Loading photos for auto-sort...", "Reading images and EXIF timestamps...");
    try {
      const inspected = await bridge.panel_studio_inspect_sources(paths, []);
      if (inspected?.status !== "success") {
        throw new Error(inspected?.message || "Could not load photos.");
      }
      if (inspected.warnings?.length) notify(inspected.warnings[0], 5000);
      await autoSortInspectedItems(inspected.items || []);
    } catch (err) {
      setStatus(err?.message || "Could not load photos for auto-sort.", "error");
      setBusy(false);
    }
  }

  async function autoSortBrowserFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const bridge = api();
    if (!bridge?.panel_studio_inspect_sources) return;
    setBusy(true, "Loading dropped photos...", "Preparing images for gemini-decision-1...");
    try {
      const uploads = [];
      for (const file of files) {
        uploads.push(await fileToUploadPayload(file));
      }
      const inspected = await bridge.panel_studio_inspect_sources([], uploads);
      if (inspected?.status !== "success") {
        throw new Error(inspected?.message || "Could not load dropped photos.");
      }
      if (inspected.warnings?.length) notify(inspected.warnings[0], 5000);
      await autoSortInspectedItems(inspected.items || []);
    } catch (err) {
      setStatus(err?.message || "Could not load dropped photos.", "error");
      setBusy(false);
    }
  }

  async function browseForAutoSort() {
    const bridge = api();
    if (bridge?.select_files) {
      const res = await bridge.select_files({
        allow_multiple: true,
        default_directory: getDefaultDirectory(),
        file_types: [
          "Site Survey Photos (*.jpg;*.jpeg;*.png;*.heic;*.heif;*.tif;*.tiff;*.bmp;*.webp)",
          "All Supported (*.jpg;*.jpeg;*.png;*.heic;*.heif;*.tif;*.tiff;*.bmp;*.webp;*.pdf)",
        ],
      });
      if (res?.status === "success" && res.paths?.length) {
        await autoSortPaths(res.paths);
      }
      return;
    }
    state.pendingBrowseTarget = { workflow: "auto_sort", bucket: null };
    const input = byId("psaFallbackFileInput");
    if (input) {
      input.value = "";
      input.click();
    }
  }

  // ------------------------------------------------------------------
  // Stage 1: Local ONNX Zero-Shot Survey Folder Pre-Filter ($0 Tokens)
  // ------------------------------------------------------------------

  function applyPrefilterResult(pfRes) {
    const kept = pfRes.kept || [];
    const dropped = pfRes.dropped || [];
    const stats = pfRes.stats || {};
    const decisionResult = pfRes.decisionResult || null;
    registerSourcesInIndex([...kept, ...dropped]);

    const activeGroup = getActiveFieldGroup();
    const splitPanels = Boolean(byId("psaAutoSortSplitCb")?.checked);
    const groupTargets = new Map();

    if (decisionResult && Array.isArray(decisionResult.assignments) && decisionResult.assignments.length) {
      const panelCount = splitPanels ? Math.max(1, Number(decisionResult.panelGroupCount) || 1) : 1;
      const reuseActive =
        activeGroup && getGroupSources(activeGroup).length === 0 && !(activeGroup.ignored?.length);
      for (let gIdx = 0; gIdx < panelCount; gIdx++) {
        if (gIdx === 0 && reuseActive) {
          groupTargets.set(0, activeGroup);
        } else if (gIdx === 0 && !splitPanels) {
          groupTargets.set(0, activeGroup);
        } else {
          const grp = createFieldGroup(state.fieldGroups.length + 1);
          state.fieldGroups.push(grp);
          groupTargets.set(gIdx, grp);
        }
      }
      state.activeFieldGroupId = groupTargets.get(0)?.id || state.activeFieldGroupId;

      const keptMap = new Map(kept.map((it) => [it.id, it]));
      for (const assign of decisionResult.assignments) {
        const item = keptMap.get(assign.id);
        if (!item) continue;
        const targetGroup = groupTargets.get(assign.panelGroupIndex || 0) || activeGroup;
        if (!targetGroup) continue;
        item.sortConfidence = assign.confidence;
        item.sortLowConfidence = Boolean(assign.lowConfidence);
        if (assign.suggestedHint && !item.hint) item.hint = assign.suggestedHint;
        if (assign.bucket === "ignore") {
          item.role = "ignore";
          item.dropReason = `gemini-decision-1: ignored (${Math.round((assign.confidence || 0) * 100)}%)`;
          targetGroup.ignored.push(item);
        } else {
          const destBucket = FIELD_BUCKETS.includes(assign.bucket) ? assign.bucket : "breakers";
          item.role = destBucket;
          item.selected = true;
          targetGroup.buckets[destBucket].push(item);
        }
      }
    } else if (activeGroup) {
      // Local ONNX buckets only (no Decision API refinement)
      groupTargets.set(0, activeGroup);
      for (const item of kept) {
        const destBucket = FIELD_BUCKETS.includes(item.role) ? item.role : "breakers";
        item.role = destBucket;
        item.selected = true;
        item.sortConfidence = item.panelScore;
        item.sortLowConfidence = (item.panelScore || 0) < 0.6;
        activeGroup.buckets[destBucket].push(item);
      }
    }

    // Place locally dropped photos into the first panel tab's non-destructive Ignored tray
    const firstGroup = groupTargets.get(0) || activeGroup;
    if (firstGroup && dropped.length) {
      for (const d of dropped) {
        d.role = "ignore";
        firstGroup.ignored.push(d);
      }
    }

    const savedK = ((stats.estimatedTokensSaved || 0) / 1000).toFixed(0);
    const secs = ((stats.elapsedMs || 0) / 1000).toFixed(1);
    const panelNote = decisionResult && splitPanels ? ` across ${groupTargets.size} panel tab(s)` : "";
    const msg =
      `Local ONNX scanned ${stats.totalScanned || 0} photos in ${secs}s ($0 tokens) → kept ${stats.keptCount || 0} panel candidate(s)${panelNote}, ` +
      `filtered ${stats.nonPanelDropped || 0} non-panel & ${stats.duplicateDropped || 0} duplicate(s) (~${savedK}k tokens saved).`;
    setStatus(msg, "success");
    if (pfRes.decisionWarning) notify(pfRes.decisionWarning, 6000);
    else notify(msg, 5500);
    renderAll();

    const dlg = byId("panelStudioDlg");
    if (!dlg?.open) {
      showReadyToast("Survey folder pre-filtered", msg, false);
    }
  }

  async function scanSurveyFolderWithLocalPrefilter() {
    if (state.bgJob.running) {
      setStatus("A background job is already running — wait for it to finish.", "");
      return;
    }
    const bridge = api();
    if (!bridge?.select_folder || !bridge?.panel_studio_start_prefilter || !bridge?.panel_studio_get_job_status) {
      notify("Local folder pre-filter backend is not available.");
      return;
    }
    const picked = await bridge.select_folder(getDefaultDirectory());
    if (picked?.status !== "success" || !picked.path) return;

    const sensitivity = byId("psaPrefilterSensitivity")?.value || "balanced";
    const splitPanels = Boolean(byId("psaAutoSortSplitCb")?.checked);

    try {
      hideReadyToast();
      const startRes = await bridge.panel_studio_start_prefilter({
        folderPath: picked.path,
        sensitivity,
        dedupe: true,
        refineWithDecision: Boolean(state.hasApiKey),
        splitPanels,
      });
      if (startRes?.status !== "started") {
        throw new Error(startRes?.message || "Could not start local pre-filter.");
      }

      clearBgJobTimers();
      state.bgJob.running = true;
      state.bgJob.jobId = startRes.jobId;
      state.bgJob.kind = "prefilter";
      state.bgJob.progress = 6;
      state.bgJob.message = "Scanning survey folder locally with ONNX CLIP ($0 tokens)...";
      state.bgJob.startedAt = Date.now();
      state.bgJob.activityId = "";

      if (typeof window.beginActivity === "function") {
        try {
          state.bgJob.activityId = window.beginActivity({
            toolId: "toolPanelScheduleStudio",
            label: "Panel Schedule Pre-Filter (Local ONNX)",
            message: state.bgJob.message,
            progress: 6,
            canRerun: false,
            canCancel: false,
          });
        } catch (_err) {
          state.bgJob.activityId = "";
        }
      }

      renderBgProgressBanner();
      renderFooterControls();
      state.bgJob.tickTimer = window.setInterval(renderBgProgressBanner, 1000);
      state.bgJob.pollTimer = window.setTimeout(() => void pollBgAnalysisJob(), 600);
    } catch (err) {
      setStatus(err?.message || "Local pre-filter failed.", "error");
      notify(err?.message || "Local pre-filter failed.", 6000);
    }
  }

  function movePhotoBetweenBuckets(group, fromBucket, index, toBucket) {
    if (!group || fromBucket === toBucket) return;
    const sourceArr = fromBucket === "ignore" ? group.ignored : group.buckets[fromBucket];
    if (!sourceArr || index < 0 || index >= sourceArr.length) return;
    const [item] = sourceArr.splice(index, 1);
    item.sortLowConfidence = false;
    if (toBucket === "ignore") {
      item.role = "ignore";
      group.ignored.push(item);
    } else if (FIELD_BUCKETS.includes(toBucket)) {
      item.role = toBucket;
      item.selected = true;
      group.buckets[toBucket].push(item);
    }
    renderFieldWorkflow();
    renderFooterControls();
  }

  function setActivePasteBucket(bucket) {
    if (!FIELD_BUCKETS.includes(bucket)) return;
    state.activePasteBucket = bucket;
    for (const card of document.querySelectorAll(".psa-bucket")) {
      const isTarget = card.dataset.bucket === bucket;
      card.classList.toggle("is-paste-target", isTarget);
      const chip = card.querySelector(".psa-paste-chip");
      if (chip) chip.hidden = !isTarget;
    }
  }

  // ------------------------------------------------------------------
  // Perceptual Duplicate Detection & Token Optimization Advisor
  // ------------------------------------------------------------------

  function dhashHammingDistance(hexA, hexB) {
    if (!hexA || !hexB || hexA.length !== 16 || hexB.length !== 16) return 999;
    let dist = 0;
    for (let i = 0; i < 16; i++) {
      let x = parseInt(hexA[i], 16) ^ parseInt(hexB[i], 16);
      while (x) {
        dist += x & 1;
        x >>= 1;
      }
    }
    return dist;
  }

  function findNearDuplicateIds(items) {
    // Returns Set of IDs that are duplicates/near-duplicates of an earlier item in the list.
    const dupes = new Set();
    const kept = [];
    for (const item of items || []) {
      const hash = String(item?.dhash || "").trim();
      if (!hash) {
        kept.push(item);
        continue;
      }
      const match = kept.find((prev) => dhashHammingDistance(prev.dhash, hash) <= 10);
      if (match) {
        dupes.add(item.id);
      } else {
        kept.push(item);
      }
    }
    return dupes;
  }

  function renderTokenAdvisor() {
    const bar = byId("psaTokenAdvisor");
    const msgEl = byId("psaTokenAdvisorMsg");
    const rmBtn = byId("psaRemoveDupesBtn");
    if (!bar || !msgEl) return;

    let activeItems = [];
    let redundantBucketNote = "";
    if (state.workflow === "field_photos") {
      const grp = getActiveFieldGroup();
      activeItems = getGroupSources(grp);
      if (grp) {
        const denseBuckets = [];
        if ((grp.buckets.nameplate || []).length > 2) denseBuckets.push(`${grp.buckets.nameplate.length} nameplate photos`);
        if ((grp.buckets.breakers || []).length > 3) denseBuckets.push(`${grp.buckets.breakers.length} breaker photos`);
        if ((grp.buckets.directory || []).length > 2) denseBuckets.push(`${grp.buckets.directory.length} directory photos`);
        if ((grp.buckets.main_breaker || []).length > 2) denseBuckets.push(`${grp.buckets.main_breaker.length} main breaker photos`);
        if (denseBuckets.length) {
          redundantBucketNote = `Multiple shots in ${denseBuckets.join(", ")} — keep only the sharpest photo per section.`;
        }
      }
    } else {
      activeItems = getSelectedDrawingSources();
    }

    const dupes = findNearDuplicateIds(activeItems);
    state.duplicateIds = dupes;

    const count = activeItems.length;
    if (count === 0) {
      bar.hidden = true;
      return;
    }

    // Rough visual estimate (~1.2k tokens per field photo, ~2.0k per dense drawing sheet)
    const tokensPerImage = state.workflow === "field_photos" ? 1.2 : 2.0;
    const estTokensK = (count * tokensPerImage).toFixed(1);
    const hasHighCount = state.workflow === "field_photos" ? count >= 5 : count >= 4;
    const needsWarning = dupes.size > 0 || Boolean(redundantBucketNote) || hasHighCount;

    bar.hidden = false;
    bar.classList.toggle("is-info", !needsWarning);

    const bits = [];
    if (dupes.size > 0) {
      bits.push(
        `${dupes.size} near-duplicate image${dupes.size === 1 ? "" : "s"} detected — remove duplicates to save input tokens and speed up Gemini 4 Hydrogen.`
      );
    }
    if (redundantBucketNote) {
      bits.push(redundantBucketNote);
    } else if (hasHighCount) {
      bits.push(
        `${count} images selected (~${estTokensK}k est. image tokens). Remove any blurry, unnecessary, or overlapping photos to reduce token usage and run time.`
      );
    } else if (dupes.size === 0) {
      bits.push(
        `${count} image${count === 1 ? "" : "s"} ready (~${estTokensK}k est. image tokens). Tip: remove unnecessary or duplicate photos before running to keep extraction fast.`
      );
    }
    msgEl.textContent = bits.join(" ");
    if (rmBtn) {
      rmBtn.hidden = dupes.size === 0;
      rmBtn.textContent = `Remove ${dupes.size} Duplicate${dupes.size === 1 ? "" : "s"}`;
    }
  }

  function removeDetectedDuplicates() {
    if (!state.duplicateIds.size) return;
    let removed = 0;
    if (state.workflow === "field_photos") {
      const grp = getActiveFieldGroup();
      if (grp) {
        for (const bucket of FIELD_BUCKETS) {
          const before = grp.buckets[bucket].length;
          grp.buckets[bucket] = grp.buckets[bucket].filter((it) => !state.duplicateIds.has(it.id));
          removed += before - grp.buckets[bucket].length;
        }
      }
    } else {
      const before = state.drawingSources.length;
      state.drawingSources = state.drawingSources.filter((it) => !state.duplicateIds.has(it.id));
      removed += before - state.drawingSources.length;
    }
    state.duplicateIds = new Set();
    renderAll();
    setStatus(`Removed ${removed} duplicate image${removed === 1 ? "" : "s"}.`, "success");
  }

  // ------------------------------------------------------------------
  // Non-Blocking Background Extraction with Gemini 4 Hydrogen
  // ------------------------------------------------------------------

  function formatElapsedClock(totalSec) {
    const s = Math.max(0, Math.floor(totalSec || 0));
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
  }

  function clearBgJobTimers() {
    if (state.bgJob.pollTimer) {
      window.clearTimeout(state.bgJob.pollTimer);
      state.bgJob.pollTimer = 0;
    }
    if (state.bgJob.tickTimer) {
      window.clearInterval(state.bgJob.tickTimer);
      state.bgJob.tickTimer = 0;
    }
  }

  function renderBgProgressBanner() {
    const banner = byId("psaBgProgressBanner");
    const msgEl = byId("psaBgBannerMsg");
    const fill = byId("psaBgBarFill");
    const elapsedEl = byId("psaBgElapsed");
    if (!banner) return;
    banner.hidden = !state.bgJob.running;
    if (!state.bgJob.running) return;
    if (msgEl) msgEl.textContent = state.bgJob.message || "Analyzing in background with Gemini 4 Hydrogen...";
    if (fill) fill.style.width = `${Math.max(8, Math.min(98, state.bgJob.progress || 10))}%`;
    if (elapsedEl) {
      const sec = state.bgJob.startedAt ? (Date.now() - state.bgJob.startedAt) / 1000 : 0;
      elapsedEl.textContent = formatElapsedClock(sec);
    }
  }

  function showReadyToast(title, subtitle, isError = false) {
    const toast = byId("psaReadyToast");
    const tEl = byId("psaReadyToastTitle");
    const sEl = byId("psaReadyToastSub");
    const openBtn = byId("psaReadyToastOpenBtn");
    if (!toast) return;
    toast.classList.toggle("is-error", Boolean(isError));
    if (tEl) tEl.textContent = title;
    if (sEl) sEl.textContent = subtitle;
    if (openBtn) openBtn.textContent = isError ? "Open Studio" : "Review Now";
    toast.hidden = false;
  }

  function hideReadyToast() {
    const toast = byId("psaReadyToast");
    if (toast) toast.hidden = true;
  }

  async function applyExtractionResult(res) {
    const viewerUrls = res.viewerUrls || {};
    for (const [srcId, dataUrl] of Object.entries(viewerUrls)) {
      const src = state.sourceById.get(srcId);
      if (src && dataUrl) src.viewerDataUrl = dataUrl;
    }

    state.panels = (res.panels || []).map((p) => ({ ...p, includeInExport: true }));
    state.activePanelId = state.panels[0]?.id || "";
    state.step = "review";
    state.flagCursor = -1;
    state.lastExportedPath = "";

    await selectViewerSource(0);

    const totalFlagged = state.panels.reduce((acc, p) => acc + computePanelSummary(p).flaggedCount, 0);
    const summaryText =
      `Extracted ${state.panels.length} panel${state.panels.length === 1 ? "" : "s"} using ${res.model || state.modelName}.` +
      (totalFlagged > 0 ? ` ${totalFlagged} item${totalFlagged === 1 ? "" : "s"} flagged for review.` : " Ready to review & export.");

    setStatus(summaryText, "success");
    renderAll();

    if (state.bgJob.activityId && typeof window.completeActivity === "function") {
      try {
        window.completeActivity(state.bgJob.activityId, { message: summaryText });
      } catch (_err) {
        // ignore
      }
    }

    const dlg = byId("panelStudioDlg");
    if (!dlg?.open) {
      showReadyToast(
        `${state.panels.length} panel schedule${state.panels.length === 1 ? "" : "s"} ready`,
        summaryText,
        false
      );
      notify(`Panel Schedule AI Studio finished: ${state.panels.length} panel(s) ready to review.`, 6000);
    } else {
      notify(summaryText, 4500);
    }
  }

  async function pollBgAnalysisJob() {
    if (!state.bgJob.running || !state.bgJob.jobId) return;
    const bridge = api();
    if (!bridge?.panel_studio_get_job_status) return;
    try {
      const status = await bridge.panel_studio_get_job_status(state.bgJob.jobId);
      if (!state.bgJob.running) return;

      if (status?.status === "running") {
        state.bgJob.progress = Number(status.progress) || state.bgJob.progress;
        state.bgJob.message = status.message || state.bgJob.message;
        renderBgProgressBanner();
        if (state.bgJob.activityId && typeof window.updateActivity === "function") {
          try {
            window.updateActivity(state.bgJob.activityId, {
              progress: state.bgJob.progress,
              message: state.bgJob.message,
            });
          } catch (_err) {
            // ignore
          }
        }
        state.bgJob.pollTimer = window.setTimeout(() => void pollBgAnalysisJob(), 1500);
        return;
      }

      clearBgJobTimers();
      state.bgJob.running = false;
      renderBgProgressBanner();
      renderFooterControls();

      if (status?.status === "success" && status.result) {
        const jobKind = state.bgJob.kind || "analyze";
        state.bgJob.kind = "analyze";
        if (jobKind === "prefilter") {
          if (state.bgJob.activityId && typeof window.completeActivity === "function") {
            try {
              window.completeActivity(state.bgJob.activityId, { message: status.message || "Pre-filter complete." });
            } catch (_err) {
              // ignore
            }
          }
          applyPrefilterResult(status.result);
        } else {
          await applyExtractionResult(status.result);
        }
      } else {
        const errMsg = status?.error || status?.message || "Gemini 4 Hydrogen extraction failed.";
        setStatus(errMsg, "error");
        if (state.bgJob.activityId && typeof window.failActivity === "function") {
          try {
            window.failActivity(state.bgJob.activityId, { message: errMsg });
          } catch (_err) {
            // ignore
          }
        }
        const dlg = byId("panelStudioDlg");
        if (!dlg?.open) {
          showReadyToast("Panel Schedule AI Studio failed", errMsg, true);
        }
        notify(errMsg, 6000);
      }
    } catch (err) {
      // Transient polling hiccup: retry briefly
      if (state.bgJob.running) {
        state.bgJob.pollTimer = window.setTimeout(() => void pollBgAnalysisJob(), 2500);
      }
    }
  }

  function buildAnalysisGroupsPayload() {
    const groups = [];
    const stripSource = (s) => ({
      id: s.id,
      kind: s.kind,
      name: s.name,
      path: s.path,
      pageIndex: s.pageIndex,
      pageLabel: s.pageLabel,
      role: s.role,
      hint: s.hint,
      detectedTags: Array.isArray(s.detectedTags) ? s.detectedTags : [],
      selected: true,
      viewerDataUrl: s.viewerDataUrl ? "cached" : "",
    });

    if (state.workflow === "field_photos") {
      for (const grp of getReadyFieldGroups()) {
        groups.push({
          mode: "field_photos",
          panelName: grp.panelName,
          condition: grp.condition,
          sources: getGroupSources(grp).map(stripSource),
        });
      }
    } else {
      const selectedDrawings = getSelectedDrawingSources();
      if (selectedDrawings.length) {
        groups.push({
          mode: "as_built_drawing",
          panelName: state.drawingPanelNameHint,
          sources: selectedDrawings.map(stripSource),
        });
      }
    }
    return groups;
  }

  async function runHydrogenAnalysis() {
    if (state.bgJob.running) {
      setStatus("Extraction is already running in the background — you can minimize and keep working.", "");
      return;
    }
    const groups = buildAnalysisGroupsPayload();
    if (!groups.length) {
      setStatus(
        state.workflow === "field_photos"
          ? "Add at least one photo (breakers, directory, or panelboard tag) to extract."
          : "Select at least one PDF page or drawing image to extract.",
        "error"
      );
      return;
    }
    const bridge = api();
    if (!bridge?.panel_studio_start_analyze && !bridge?.panel_studio_analyze) {
      setStatus("Panel Schedule Studio backend is unavailable.", "error");
      return;
    }

    const totalImages = groups.reduce((acc, g) => acc + g.sources.length, 0);
    const startMsg =
      state.workflow === "field_photos"
        ? `Analyzing ${groups.length} panel${groups.length === 1 ? "" : "s"} (${totalImages} photo${totalImages === 1 ? "" : "s"}) in background with Gemini 4 Hydrogen...`
        : `Analyzing ${totalImages} drawing sheet${totalImages === 1 ? "" : "s"} in background with Gemini 4 Hydrogen...`;

    hideReadyToast();

    // Non-blocking background execution path (default)
    if (bridge.panel_studio_start_analyze && bridge.panel_studio_get_job_status) {
      try {
        const startRes = await bridge.panel_studio_start_analyze({ groups });
        if (startRes?.status !== "started" && startRes?.status !== "already_running") {
          throw new Error(startRes?.message || "Could not start background extraction.");
        }
        clearBgJobTimers();
        state.bgJob.running = true;
        state.bgJob.jobId = startRes.jobId;
        state.bgJob.kind = "analyze";
        state.bgJob.progress = 10;
        state.bgJob.message = startMsg;
        state.bgJob.startedAt = Date.now();
        state.bgJob.activityId = "";

        if (typeof window.beginActivity === "function") {
          try {
            state.bgJob.activityId = window.beginActivity({
              toolId: "toolPanelScheduleStudio",
              label: "Panel Schedule AI Studio",
              message: startMsg,
              progress: 10,
              canRerun: false,
              canCancel: false,
            });
          } catch (_err) {
            state.bgJob.activityId = "";
          }
        }

        setStatus("Running in background — click 'Minimize & Keep Working' or Close to use the rest of the app.", "");
        renderBgProgressBanner();
        renderFooterControls();

        state.bgJob.tickTimer = window.setInterval(renderBgProgressBanner, 1000);
        state.bgJob.pollTimer = window.setTimeout(() => void pollBgAnalysisJob(), 1200);
        return;
      } catch (err) {
        setStatus(err?.message || "Could not start extraction.", "error");
        notify(err?.message || "Could not start extraction.", 6000);
        return;
      }
    }

    // Fallback synchronous path if background endpoints are absent
    setBusy(true, "Analyzing with Gemini 4 Hydrogen...", startMsg);
    try {
      const res = await bridge.panel_studio_analyze({ groups });
      if (res?.status !== "success") {
        throw new Error(res?.message || "Gemini 4 Hydrogen extraction failed.");
      }
      await applyExtractionResult(res);
    } catch (err) {
      setStatus(err?.message || "Extraction failed.", "error");
      notify(err?.message || "Extraction failed.", 6000);
    } finally {
      setBusy(false);
    }
  }

  async function estimateMissingKvaForActivePanel() {
    const panel = getActivePanel();
    if (!panel) return;
    const bridge = api();
    if (!bridge?.panel_studio_estimate_kva) return;
    try {
      const res = await bridge.panel_studio_estimate_kva(panel, false);
      if (res?.status === "success" && res.panel) {
        const idx = state.panels.findIndex((p) => p.id === panel.id);
        if (idx >= 0) {
          state.panels[idx] = {
            ...res.panel,
            includeInExport: panel.includeInExport,
            sourceIds: panel.sourceIds || [],
          };
        }
        renderReviewPane();
        setStatus(`Estimated missing kVA on Panel "${panel.panelName}" (extracted values kept intact).`, "success");
      }
    } catch (err) {
      setStatus(err?.message || "Could not estimate kVA.", "error");
    }
  }

  function clearEstimatedKvaForActivePanel() {
    const panel = getActivePanel();
    if (!panel) return;
    let cleared = 0;
    for (const ckt of panel.circuits || []) {
      if (ckt.kvaEstimated) {
        ckt.phaseKva = new Array(Math.max(Number(ckt.poles) || 1, 1)).fill(null);
        ckt.kvaEstimated = false;
        cleared += 1;
      }
    }
    renderReviewPane();
    setStatus(cleared ? `Cleared ${cleared} estimated kVA circuit(s).` : "No estimated kVA values to clear.");
  }

  // ------------------------------------------------------------------
  // Interactive Source Viewer (Cursor-Anchored Zoom / Pan / Rotate)
  // ------------------------------------------------------------------

  const VIEWER_MIN_ZOOM = 0.25;
  const VIEWER_MAX_ZOOM = 12;

  function clampViewerPan() {
    const stage = byId("psaViewerStage");
    const img = byId("psaViewerImg");
    if (!stage || !img) return;
    if (state.zoom <= 1.001) {
      state.panX = 0;
      state.panY = 0;
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    const baseW = img.offsetWidth || stageRect.width * 0.9;
    const baseH = img.offsetHeight || stageRect.height * 0.9;
    const rotated = state.rotation % 180 !== 0;
    const scaledW = (rotated ? baseH : baseW) * state.zoom;
    const scaledH = (rotated ? baseW : baseH) * state.zoom;
    // Allow panning comfortably across the entire image while keeping an edge reachable
    const maxPanX = Math.max(0, (scaledW - stageRect.width) / 2 + stageRect.width * 0.2);
    const maxPanY = Math.max(0, (scaledH - stageRect.height) / 2 + stageRect.height * 0.2);
    state.panX = Math.min(maxPanX, Math.max(-maxPanX, state.panX));
    state.panY = Math.min(maxPanY, Math.max(-maxPanY, state.panY));
  }

  function resetViewerTransform() {
    state.zoom = 1;
    state.panX = 0;
    state.panY = 0;
    state.rotation = 0;
    applyViewerTransform();
  }

  function zoomViewerTo(targetZoom, clientX = null, clientY = null) {
    const stage = byId("psaViewerStage");
    const oldZoom = state.zoom || 1;
    const newZoom = Math.min(VIEWER_MAX_ZOOM, Math.max(VIEWER_MIN_ZOOM, targetZoom));
    if (Math.abs(newZoom - oldZoom) < 0.0005) return;

    if (stage && typeof clientX === "number" && typeof clientY === "number") {
      const rect = stage.getBoundingClientRect();
      const mx = clientX - (rect.left + rect.width / 2);
      const my = clientY - (rect.top + rect.height / 2);
      const ratio = newZoom / oldZoom;
      state.panX = mx - (mx - state.panX) * ratio;
      state.panY = my - (my - state.panY) * ratio;
    } else {
      const ratio = newZoom / oldZoom;
      state.panX *= ratio;
      state.panY *= ratio;
    }

    state.zoom = newZoom;
    clampViewerPan();
    applyViewerTransform();
  }

  function applyViewerTransform() {
    const img = byId("psaViewerImg");
    if (!img) return;
    img.style.transform =
      `translate3d(calc(-50% + ${state.panX}px), calc(-50% + ${state.panY}px), 0) ` +
      `scale(${state.zoom}) rotate(${state.rotation}deg)`;
    const zoomLabel = byId("psaZoomLabel");
    if (zoomLabel) zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
  }

  async function selectViewerSource(index) {
    const sources = getViewerSourcesForActivePanel();
    const img = byId("psaViewerImg");
    const caption = byId("psaViewerCaption");
    const loading = byId("psaViewerLoading");
    if (!sources.length) {
      if (img) img.removeAttribute("src");
      if (caption) caption.textContent = "No source image attached";
      renderViewerFilmstrip();
      return;
    }

    const clamped = Math.max(0, Math.min(index, sources.length - 1));
    state.activeSourceIndex = clamped;
    const src = sources[clamped];
    resetViewerTransform();
    renderViewerFilmstrip();

    const roleTag = ROLE_SHORT_LABELS[src.role] || "";
    const titleText = src.pageLabel || src.name || `Source ${clamped + 1}`;
    if (caption) caption.textContent = roleTag ? `[${roleTag}] ${titleText}` : titleText;

    if (!img) return;
    if (src.viewerDataUrl) {
      if (loading) loading.hidden = true;
      img.src = src.viewerDataUrl;
      return;
    }

    img.src = src.thumbDataUrl || "";
    if (loading) loading.hidden = false;
    const bridge = api();
    if (bridge?.panel_studio_render_source) {
      try {
        const res = await bridge.panel_studio_render_source({
          kind: src.kind,
          path: src.path,
          pageIndex: src.pageIndex,
        });
        if (res?.status === "success" && res.viewerDataUrl) {
          src.viewerDataUrl = res.viewerDataUrl;
          if (state.activeSourceIndex === clamped) {
            img.src = src.viewerDataUrl;
          }
        }
      } catch (err) {
        console.warn("High-res viewer render failed:", err);
      } finally {
        if (loading) loading.hidden = true;
      }
    } else if (loading) {
      loading.hidden = true;
    }
  }

  // ------------------------------------------------------------------
  // Excel Export
  // ------------------------------------------------------------------

  async function chooseExportPath() {
    const bridge = api();
    if (!bridge) return;
    if (state.exportMode === "existing") {
      const res = await bridge.select_files({
        allow_multiple: false,
        default_directory: getDefaultDirectory(),
        file_types: ["Excel Workbooks (*.xls;*.xlsx)", "Excel 97-2003 (*.xls)", "Excel Workbook (*.xlsx)"],
      });
      if (res?.status === "success" && res.paths?.[0]) {
        state.exportPath = res.paths[0];
        renderFooterControls();
      }
      return;
    }
    const activeNames = state.panels.filter((p) => p.includeInExport).map((p) => p.panelName);
    const defaultName = activeNames.length === 1 ? `Panel ${activeNames[0]}` : "Panel Schedules";
    const res = await bridge.panel_studio_choose_save_path(
      defaultName,
      state.exportFormat,
      getDefaultDirectory()
    );
    if (res?.status === "success" && res.path) {
      state.exportPath = res.path;
      renderFooterControls();
    }
  }

  function collectFlaggedExportPanels(includedPanels) {
    const flagged = [];
    for (const panel of includedPanels || []) {
      const flaggedCircuits = (panel.circuits || [])
        .filter((c) => c.confidence === "medium" || c.confidence === "low")
        .sort((a, b) => Number(a.circuitNumber) - Number(b.circuitNumber));
      const warnings = (panel.headerWarnings || []).filter((w) => String(w || "").trim());
      if (flaggedCircuits.length || warnings.length) {
        flagged.push({
          panel,
          flaggedCircuits,
          warnings,
        });
      }
    }
    return flagged;
  }

  function hideExportFlagCheckup() {
    const overlay = byId("psaFlagCheckOverlay");
    if (overlay) overlay.hidden = true;
  }

  function jumpToPanelFlags(panelId) {
    hideExportFlagCheckup();
    state.activePanelId = panelId;
    state.flagCursor = -1;
    renderReviewPane();
    void selectViewerSource(0);
    window.requestAnimationFrame(() => jumpToNextFlag());
  }

  function showExportFlagCheckup(flaggedEntries) {
    const overlay = byId("psaFlagCheckOverlay");
    const sub = byId("psaCheckupSub");
    const list = byId("psaCheckupList");
    if (!overlay || !list) return;

    const totalCircuits = flaggedEntries.reduce((acc, e) => acc + e.flaggedCircuits.length, 0);
    const totalWarnings = flaggedEntries.reduce((acc, e) => acc + e.warnings.length, 0);
    const parts = [];
    if (totalCircuits) parts.push(`${totalCircuits} flagged circuit${totalCircuits === 1 ? "" : "s"}`);
    if (totalWarnings) parts.push(`${totalWarnings} header warning${totalWarnings === 1 ? "" : "s"}`);

    if (sub) {
      sub.textContent =
        `${flaggedEntries.length} panel${flaggedEntries.length === 1 ? "" : "s"} selected for export ` +
        `${flaggedEntries.length === 1 ? "has" : "have"} ${parts.join(" and ")}. ` +
        "Would you like to review them first, or continue exporting all selected panels to Excel?";
    }

    list.replaceChildren();
    for (const entry of flaggedEntries) {
      const row = el("button", "psa-checkup-row");
      row.type = "button";
      const copy = el("div");
      copy.appendChild(el("div", "psa-checkup-row-title", `Panel ${entry.panel.panelName || "?"}`));

      const detailBits = [];
      if (entry.flaggedCircuits.length) {
        const previewCkts = entry.flaggedCircuits
          .slice(0, 6)
          .map((c) => `Ckt ${c.circuitNumber}`)
          .join(", ");
        const more = entry.flaggedCircuits.length > 6 ? ` +${entry.flaggedCircuits.length - 6} more` : "";
        detailBits.push(`Flagged circuits: ${previewCkts}${more}`);
      }
      if (entry.warnings.length) {
        detailBits.push(entry.warnings[0]);
      }
      copy.appendChild(el("div", "psa-checkup-row-detail", detailBits.join(" • ")));
      row.appendChild(copy);
      row.appendChild(el("span", "psa-checkup-row-jump", "Review →"));
      row.addEventListener("click", () => jumpToPanelFlags(entry.panel.id));
      list.appendChild(row);
    }

    overlay.dataset.firstFlaggedPanelId = flaggedEntries[0]?.panel?.id || "";
    overlay.hidden = false;
  }

  async function runExcelExport({ skipFlagCheckup = false } = {}) {
    const included = state.panels.filter((p) => p.includeInExport);
    if (!included.length) {
      setStatus("Check at least one panel tab to include in the export.", "error");
      return;
    }
    if (!skipFlagCheckup) {
      const flaggedEntries = collectFlaggedExportPanels(included);
      if (flaggedEntries.length) {
        showExportFlagCheckup(flaggedEntries);
        return;
      }
    }
    hideExportFlagCheckup();
    if (!state.exportPath) {
      await chooseExportPath();
      if (!state.exportPath) return;
    }
    const bridge = api();
    if (!bridge?.panel_studio_export_excel) {
      setStatus("Excel export backend is not ready.", "error");
      return;
    }
    setBusy(
      true,
      "Writing ACIES Excel workbook...",
      `Populating ${included.length} panel sheet(s) from Template.xlsx with NEC demand formulas intact.`
    );
    try {
      const res = await bridge.panel_studio_export_excel({
        panels: included,
        outputPath: state.exportPath,
        mode: state.exportMode,
        replaceExistingSheets: state.replaceExistingSheets,
      });
      if (res?.status !== "success") {
        throw new Error(res?.message || "Excel export failed.");
      }
      state.lastExportedPath = res.path;
      const sheetList = (res.sheets || []).join(", ");
      setStatus(`Exported ${res.sheets?.length || 0} sheet(s) (${sheetList}) to ${res.path}`, "success");
      notify(`Saved Excel panel schedule: ${sheetList}`, 5000);
      renderFooterControls();
    } catch (err) {
      setStatus(err?.message || "Excel export failed.", "error");
      notify(err?.message || "Excel export failed.", 6000);
    } finally {
      setBusy(false);
    }
  }

  async function openExportedPath(revealInFolder = false) {
    if (!state.lastExportedPath) return;
    const bridge = api();
    if (bridge?.panel_studio_open_path) {
      await bridge.panel_studio_open_path(state.lastExportedPath, revealInFolder);
    }
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------

  function renderHeader() {
    const btnSources = byId("psaStepSourcesBtn");
    const btnReview = byId("psaStepReviewBtn");
    if (btnSources) btnSources.classList.toggle("is-active", state.step === "sources");
    if (btnReview) {
      btnReview.classList.toggle("is-active", state.step === "review");
      btnReview.disabled = state.panels.length === 0;
      btnReview.textContent = state.panels.length
        ? `2. Review & Export (${state.panels.length})`
        : "2. Review & Export";
    }

    const pill = byId("psaModelPill");
    const pillText = byId("psaModelPillText");
    if (pill && pillText) {
      if (!state.hasApiKey) {
        pill.classList.add("is-warn");
        pillText.textContent = "API Key Needed (Settings)";
      } else {
        pill.classList.remove("is-warn");
        pillText.textContent = "Gemini 4 Hydrogen • Free Tier";
      }
    }

    const sourcesView = byId("psaSourcesView");
    const reviewView = byId("psaReviewView");
    if (sourcesView) sourcesView.hidden = state.step !== "sources";
    if (reviewView) reviewView.hidden = state.step !== "review";
  }

  function renderFieldWorkflow() {
    renderTokenAdvisor();
    const group = getActiveFieldGroup();
    if (!group) return;

    // Panel group tabs
    const tabsHost = byId("psaFieldGroupTabs");
    if (tabsHost) {
      tabsHost.replaceChildren();
      state.fieldGroups.forEach((grp, idx) => {
        const count = getGroupSources(grp).length;
        const label = grp.panelName ? `Panel ${grp.panelName}` : `Panel ${idx + 1}`;
        const tab = el("button", `psa-group-tab${grp.id === group.id ? " is-active" : ""}`);
        tab.type = "button";
        tab.appendChild(el("span", "", label));
        tab.appendChild(el("span", "psa-group-tab-count", String(count)));
        tab.addEventListener("click", () => {
          state.activeFieldGroupId = grp.id;
          renderFieldWorkflow();
        });
        tabsHost.appendChild(tab);
      });
    }

    const removeBtn = byId("psaRemoveFieldGroupBtn");
    if (removeBtn) removeBtn.disabled = state.fieldGroups.length <= 1;

    const nameInp = byId("psaGroupPanelName");
    if (nameInp && nameInp.value !== group.panelName) {
      nameInp.value = group.panelName;
    }
    const condSel = byId("psaGroupCondition");
    if (condSel) condSel.value = group.condition || "EXISTING";

    setActivePasteBucket(state.activePasteBucket);

    const buildPhotoCard = (item, idx, currentBucket) => {
      const isDupe = currentBucket !== "ignore" && state.duplicateIds.has(item.id);
      const card = el(
        "div",
        `psa-bucket-item${item.sortLowConfidence ? " is-low-conf" : ""}${isDupe ? " is-duplicate" : ""}`
      );
      card.draggable = true;
      card.addEventListener("dragstart", (e) => {
        // Don't start card drag when selecting text inside an input/select
        if (e.target instanceof Element && e.target.closest("input, select, button")) {
          e.preventDefault();
          return;
        }
        state.draggedPhoto = {
          groupId: group.id,
          fromBucket: currentBucket,
          index: idx,
          itemId: item.id,
        };
        card.classList.add("is-dragging-card");
        if (e.dataTransfer) {
          e.dataTransfer.effectAllowed = "move";
          try {
            e.dataTransfer.setData("application/x-psa-photo", JSON.stringify(state.draggedPhoto));
          } catch (_err) {
            // ignore
          }
        }
      });
      card.addEventListener("dragend", () => {
        card.classList.remove("is-dragging-card");
        state.draggedPhoto = null;
        for (const node of document.querySelectorAll(".psa-bucket.is-dragover, .psa-ignored-tray.is-dragover")) {
          node.classList.remove("is-dragover");
        }
      });

      const thumb = el("div", "psa-bucket-thumb");
      thumb.title = "Click to view fullscreen • Drag card to move to another bucket";
      thumb.addEventListener("click", (e) => {
        e.stopPropagation();
        void openLightbox(
          item,
          { workflow: "field_photos", groupId: group.id, bucket: currentBucket, index: idx },
          false
        );
      });
      const img = document.createElement("img");
      img.src = item.thumbDataUrl || item.viewerDataUrl || "";
      img.alt = item.pageLabel || item.name;
      img.draggable = false;
      thumb.appendChild(img);

      const actionBar = el("div", "psa-thumb-actions");
      const viewBtn = el("button", "psa-thumb-btn", "View");
      viewBtn.type = "button";
      viewBtn.title = "Open fullscreen";
      viewBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        void openLightbox(
          item,
          { workflow: "field_photos", groupId: group.id, bucket: currentBucket, index: idx },
          false
        );
      });
      const cropBtn = el("button", "psa-thumb-btn", "Crop");
      cropBtn.type = "button";
      cropBtn.title = "Crop a portion of this photo (e.g. nameplate tag)";
      cropBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        void openLightbox(
          item,
          { workflow: "field_photos", groupId: group.id, bucket: currentBucket, index: idx },
          true
        );
      });
      actionBar.append(viewBtn, cropBtn);
      thumb.appendChild(actionBar);

      if (typeof item.sortConfidence === "number") {
        const pct = Math.round(item.sortConfidence * 100);
        const badge = el(
          "span",
          `psa-conf-badge${item.sortLowConfidence ? " is-low" : ""}`,
          item.sortLowConfidence ? `${pct}% check` : `${pct}%`
        );
        badge.title = "gemini-decision-1 classification confidence";
        thumb.appendChild(badge);
      }
      if (isDupe) {
        const dupeBadge = el("span", "psa-dupe-badge", "Duplicate");
        dupeBadge.title = "Looks very similar to another photo in this panel — consider removing to save input tokens";
        thumb.appendChild(dupeBadge);
      }

      const rmBtn = el("button", "psa-source-remove", "×");
      rmBtn.type = "button";
      rmBtn.title = "Remove photo";
      rmBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const arr = currentBucket === "ignore" ? group.ignored : group.buckets[currentBucket];
        arr.splice(idx, 1);
        renderFieldWorkflow();
        renderFooterControls();
      });
      thumb.appendChild(rmBtn);
      card.appendChild(thumb);

      const title = el("div", "psa-bucket-item-name", item.pageLabel || item.name);
      title.title = item.pageLabel || item.name;
      card.appendChild(title);

      if (currentBucket === "ignore" && item.dropReason) {
        const reasonEl = el("div", "psa-drop-reason", item.dropReason);
        reasonEl.title = item.dropReason;
        card.appendChild(reasonEl);
      }

      if (currentBucket === "breakers" || currentBucket === "directory") {
        const hintInp = el("input", "psa-bucket-hint-input");
        hintInp.type = "text";
        hintInp.value = item.hint || "";
        hintInp.placeholder =
          currentBucket === "breakers" ? "Ckts (e.g. 1-21 & 2-22)" : "Range (e.g. Ckts 1-42)";
        hintInp.addEventListener("click", (e) => e.stopPropagation());
        hintInp.addEventListener("input", () => {
          item.hint = hintInp.value;
        });
        card.appendChild(hintInp);
      }

      // 1-click bucket move dropdown for fast correction
      const moveSel = el("select", "psa-bucket-move-select");
      moveSel.title = "Move photo to another bucket";
      for (const opt of BUCKET_MOVE_OPTIONS) {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        if (opt.value === currentBucket) o.selected = true;
        moveSel.appendChild(o);
      }
      moveSel.addEventListener("click", (e) => e.stopPropagation());
      moveSel.addEventListener("change", () => {
        movePhotoBetweenBuckets(group, currentBucket, idx, moveSel.value);
      });
      card.appendChild(moveSel);

      return card;
    };

    // Render each of the 4 structured photo buckets
    for (const bucket of FIELD_BUCKETS) {
      const items = group.buckets[bucket] || [];
      const countEl = document.querySelector(`[data-bucket-count="${bucket}"]`);
      if (countEl) countEl.textContent = String(items.length);

      const listEl = document.querySelector(`[data-bucket-list="${bucket}"]`);
      if (!listEl) continue;
      listEl.replaceChildren();

      items.forEach((item, idx) => {
        listEl.appendChild(buildPhotoCard(item, idx, bucket));
      });
    }

    // Render Ignored / Non-Panel tray if populated
    const ignored = group.ignored || [];
    const ignoredTray = byId("psaIgnoredTray");
    const ignoredCount = byId("psaIgnoredCount");
    const ignoredList = byId("psaIgnoredList");
    if (ignoredTray) ignoredTray.hidden = ignored.length === 0;
    if (ignoredCount) ignoredCount.textContent = String(ignored.length);
    if (ignoredList) {
      ignoredList.replaceChildren();
      ignored.forEach((item, idx) => {
        ignoredList.appendChild(buildPhotoCard(item, idx, "ignore"));
      });
    }
  }

  function renderDrawingWorkflow() {
    renderTokenAdvisor();
    const hintInput = byId("psaPanelNameHint");
    if (hintInput && hintInput.value !== state.drawingPanelNameHint) {
      hintInput.value = state.drawingPanelNameHint;
    }

    const countEl = byId("psaSourcesCount");
    const selectedCount = getSelectedDrawingSources().length;
    if (countEl) {
      countEl.textContent = state.drawingSources.length
        ? `${selectedCount} of ${state.drawingSources.length} drawing sheet(s) selected`
        : "No drawing PDFs or images loaded yet";
    }

    const grid = byId("psaSourceGrid");
    if (!grid) return;
    grid.replaceChildren();

    if (!state.drawingSources.length) {
      const empty = el("div", "psa-empty-state");
      empty.appendChild(el("h3", "", "Drop as-built / record electrical PDF drawings"));
      empty.appendChild(
        el(
          "p",
          "",
          "Multi-page PDFs are split into page thumbnails so you can check only the panel schedule sheets (e.g. E07.00). Gemini 4 Hydrogen extracts every printed panel on each selected page."
        )
      );
      const addBtn = el("button", "btn-primary", "Select PDFs or Schedule Images...");
      addBtn.type = "button";
      addBtn.addEventListener("click", () => void browseForTarget("as_built_drawing"));
      empty.appendChild(addBtn);
      grid.appendChild(empty);
      return;
    }

    state.drawingSources.forEach((src, index) => {
      const isDupe = src.selected !== false && state.duplicateIds.has(src.id);
      const card = el(
        "div",
        `psa-source-card${src.selected !== false ? " is-selected" : ""}${isDupe ? " is-duplicate" : ""}`
      );
      const thumbWrap = el("div", "psa-source-thumb-wrap");
      thumbWrap.title = "Click to view fullscreen";
      thumbWrap.addEventListener("click", () => {
        void openLightbox(src, { workflow: "as_built_drawing", index }, false);
      });
      const img = document.createElement("img");
      img.src = src.thumbDataUrl || src.viewerDataUrl || "";
      img.alt = src.pageLabel || src.name;
      thumbWrap.appendChild(img);

      const checkLabel = el("label", "psa-source-check");
      checkLabel.addEventListener("click", (e) => e.stopPropagation());
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = src.selected !== false;
      cb.addEventListener("change", () => {
        src.selected = cb.checked;
        renderDrawingWorkflow();
        renderFooterControls();
      });
      checkLabel.appendChild(cb);
      checkLabel.appendChild(
        document.createTextNode(
          src.kind === "pdf_page" ? src.shortPageLabel || `P${(src.pageIndex || 0) + 1}` : `#${index + 1}`
        )
      );
      thumbWrap.appendChild(checkLabel);

      if (src.looksLikePanel) {
        thumbWrap.appendChild(el("span", "psa-source-badge", "Panel sheet"));
      }

      const srcActions = el("div", "psa-source-thumb-actions");
      const srcCropBtn = el("button", "psa-thumb-btn", "Crop");
      srcCropBtn.type = "button";
      srcCropBtn.title = "Crop a panel or region from this sheet";
      srcCropBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        void openLightbox(src, { workflow: "as_built_drawing", index }, true);
      });
      srcActions.appendChild(srcCropBtn);
      thumbWrap.appendChild(srcActions);

      const rmBtn = el("button", "psa-source-remove", "×");
      rmBtn.type = "button";
      rmBtn.title = "Remove";
      rmBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.drawingSources.splice(index, 1);
        renderDrawingWorkflow();
        renderFooterControls();
      });
      thumbWrap.appendChild(rmBtn);
      card.appendChild(thumbWrap);

      const nameEl = el("div", "psa-source-name", src.pageLabel || src.name);
      nameEl.title = src.pageLabel || src.name;
      card.appendChild(nameEl);

      const hint = el("input", "psa-input");
      hint.type = "text";
      hint.placeholder = "Optional note (e.g. Panels A, B, C)";
      hint.value = src.hint || "";
      hint.addEventListener("input", () => {
        src.hint = hint.value;
      });
      card.appendChild(hint);

      grid.appendChild(card);
    });
  }

  function renderSourcesView() {
    for (const tab of document.querySelectorAll(".psa-workflow-tab")) {
      tab.classList.toggle("is-active", tab.dataset.workflow === state.workflow);
    }
    const fieldPane = byId("psaFieldWorkflow");
    const drawingPane = byId("psaDrawingWorkflow");
    if (fieldPane) fieldPane.hidden = state.workflow !== "field_photos";
    if (drawingPane) drawingPane.hidden = state.workflow !== "as_built_drawing";

    if (state.workflow === "field_photos") {
      renderFieldWorkflow();
    } else {
      renderDrawingWorkflow();
    }
  }

  function renderViewerFilmstrip() {
    const strip = byId("psaFilmstrip");
    if (!strip) return;
    strip.replaceChildren();
    const sources = getViewerSourcesForActivePanel();
    sources.forEach((src, idx) => {
      const btn = el("button", `psa-film-item${idx === state.activeSourceIndex ? " is-active" : ""}`);
      btn.type = "button";
      btn.title = src.pageLabel || src.name;
      const img = document.createElement("img");
      img.src = src.thumbDataUrl || src.viewerDataUrl || "";
      img.alt = src.pageLabel || src.name;
      btn.appendChild(img);
      const roleTag = ROLE_SHORT_LABELS[src.role];
      if (roleTag) btn.appendChild(el("span", "psa-film-role", roleTag));
      btn.appendChild(el("span", "psa-film-idx", String(idx + 1)));
      btn.addEventListener("click", () => void selectViewerSource(idx));
      strip.appendChild(btn);
    });
  }

  function renderPanelTabs() {
    const tabsHost = byId("psaPanelTabs");
    if (!tabsHost) return;
    tabsHost.replaceChildren();

    for (const panel of state.panels) {
      const summary = computePanelSummary(panel);
      const tab = el("div", `psa-panel-tab${panel.id === state.activePanelId ? " is-active" : ""}`);
      tab.role = "button";
      tab.tabIndex = 0;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = panel.includeInExport !== false;
      cb.title = "Include this panel in Excel export";
      cb.addEventListener("click", (e) => e.stopPropagation());
      cb.addEventListener("change", () => {
        panel.includeInExport = cb.checked;
        renderFooterControls();
      });
      tab.appendChild(cb);
      tab.appendChild(el("span", "", `Panel ${panel.panelName || "?"}`));

      if (summary.flaggedCount > 0) {
        tab.appendChild(el("span", "psa-tab-flag", `${summary.flaggedCount}!`));
      }

      tab.addEventListener("click", () => {
        state.activePanelId = panel.id;
        state.flagCursor = -1;
        renderReviewPane();
        void selectViewerSource(0);
      });
      tabsHost.appendChild(tab);
    }
  }

  function renderPanelAlertBar(panel, summary) {
    const bar = byId("psaAlertBar");
    if (!bar) return;
    bar.replaceChildren();

    const warnings = panel.headerWarnings || [];
    const totalIssues = summary.flaggedCount + warnings.length;
    bar.classList.toggle("is-clean", totalIssues === 0);

    const copy = el("div", "psa-alert-copy");
    if (totalIssues > 0) {
      const msg = [];
      if (summary.flaggedCount > 0) msg.push(`${summary.flaggedCount} flagged circuit(s)`);
      if (warnings.length > 0) msg.push(warnings[0]);
      copy.appendChild(el("strong", "", "Review needed:"));
      copy.appendChild(el("span", "", msg.join(" • ")));
    } else if (panel.notes) {
      copy.appendChild(el("strong", "", "AI Note:"));
      copy.appendChild(el("span", "", panel.notes));
    } else {
      copy.appendChild(el("strong", "", "Looks clean."));
      copy.appendChild(
        el(
          "span",
          "",
          summary.missingKvaCount > 0
            ? `${summary.missingKvaCount} active circuit(s) have blank kVA — leave blank or click Estimate Missing kVA.`
            : "All extracted fields are populated and ready to export."
        )
      );
    }
    bar.appendChild(copy);

    const actions = el("div", "psa-alert-actions");
    if (summary.flaggedCount > 0) {
      const nextBtn = el("button", "btn tiny", "Next Flag");
      nextBtn.type = "button";
      nextBtn.addEventListener("click", jumpToNextFlag);
      actions.appendChild(nextBtn);

      const clearFlagsBtn = el("button", "btn tiny ghost", "Clear Flags");
      clearFlagsBtn.type = "button";
      clearFlagsBtn.addEventListener("click", () => {
        for (const c of panel.circuits || []) {
          c.confidence = "high";
          c.reviewNote = "";
        }
        panel.headerWarnings = [];
        renderReviewPane();
      });
      actions.appendChild(clearFlagsBtn);
    }

    const estBtn = el("button", "btn tiny", "Estimate Missing kVA");
    estBtn.type = "button";
    estBtn.title = "Fills only blank active circuits using ACIES estimation rules (leaves drawing kVA untouched)";
    estBtn.addEventListener("click", () => void estimateMissingKvaForActivePanel());
    actions.appendChild(estBtn);

    const hasEstimated = (panel.circuits || []).some((c) => c.kvaEstimated);
    if (hasEstimated) {
      const undoEstBtn = el("button", "btn tiny ghost", "Clear Estimates");
      undoEstBtn.type = "button";
      undoEstBtn.addEventListener("click", clearEstimatedKvaForActivePanel);
      actions.appendChild(undoEstBtn);
    }

    bar.appendChild(actions);
  }

  function renderPanelHeaderGrid(panel) {
    const grid = byId("psaPanelHeaderGrid");
    if (!grid) return;
    grid.replaceChildren();

    const addInputField = (label, key, { span2 = false, placeholder = "", transform = null } = {}) => {
      const wrap = el("div", `psa-hdr-field${span2 ? " span-2" : ""}`);
      wrap.appendChild(el("label", "", label));
      const inp = document.createElement("input");
      inp.type = "text";
      inp.value = panel[key] ?? "";
      inp.placeholder = placeholder;
      inp.addEventListener("input", () => {
        panel[key] = transform ? transform(inp.value) : inp.value;
        if (key === "panelName") renderPanelTabs();
        if (key === "voltage") renderLoadSummaryStrip(panel);
      });
      wrap.appendChild(inp);
      grid.appendChild(wrap);
    };

    const addSelectField = (label, key, options) => {
      const wrap = el("div", "psa-hdr-field");
      wrap.appendChild(el("label", "", label));
      const sel = document.createElement("select");
      for (const opt of options) {
        const o = document.createElement("option");
        o.value = String(opt.value);
        o.textContent = opt.label;
        if (String(panel[key]) === String(opt.value)) o.selected = true;
        sel.appendChild(o);
      }
      sel.addEventListener("change", () => {
        panel[key] = key === "phase" || key === "wire" || key === "circuitCount" ? Number(sel.value) : sel.value;
        if (key === "circuitCount") renderScheduleTable(panel);
        renderLoadSummaryStrip(panel);
      });
      wrap.appendChild(sel);
      grid.appendChild(wrap);
    };

    addInputField("Panel Name", "panelName", { placeholder: "e.g. D3", transform: (v) => v.toUpperCase() });
    addSelectField("Condition", "condition", [
      { value: "EXISTING", label: "EXISTING (E)" },
      { value: "NEW", label: "NEW (N)" },
    ]);
    addInputField("Voltage", "voltage", { placeholder: "120/208V", transform: (v) => v.toUpperCase() });
    addInputField("Bus Rating", "busRating", { placeholder: "225A", transform: (v) => v.toUpperCase() });
    addInputField("Main Req.", "mainRequirement", { placeholder: "MLO / 200A MCB", transform: (v) => v.toUpperCase() });
    addInputField("AIC Rating", "aicRating", { placeholder: "EXISTING / 10 KAIC", transform: (v) => v.toUpperCase() });

    addSelectField("Phase", "phase", [
      { value: 3, label: "3 Phase" },
      { value: 1, label: "1 Phase" },
    ]);
    addSelectField("Wire", "wire", [
      { value: 4, label: "4 Wire" },
      { value: 3, label: "3 Wire" },
      { value: 2, label: "2 Wire" },
    ]);
    addInputField("Mounting", "mounting", { placeholder: "SURFACE", transform: (v) => v.toUpperCase() });
    addInputField("Enclosure", "enclosure", { placeholder: "NEMA 1", transform: (v) => v.toUpperCase() });
    addInputField("Fed From", "fedFrom", { placeholder: "FED FROM PANEL 'D2'", transform: (v) => v.toUpperCase() });
    addSelectField("Spaces", "circuitCount", [
      { value: 42, label: "42 Ckts" },
      { value: 84, label: "84 Ckts" },
    ]);
  }

  function renderScheduleTable(panel) {
    const tbody = byId("psaScheduleBody");
    if (!tbody) return;
    tbody.replaceChildren();

    const totalSlots = Number(panel.circuitCount) > 42 ? 84 : 42;
    const rowsCount = totalSlots / 2;
    const slotMap = buildSlotMap(panel);

    const buildSideCells = (tr, cktNum, isLeft) => {
      const entry = slotMap.get(cktNum);
      const isContinuation = entry?.kind === "continuation";
      const ckt = entry?.circuit || null;
      const offset = entry?.offset || 0;

      const conf = ckt?.confidence || "high";
      const confClass =
        conf === "low" ? " psa-slot-low" : conf === "medium" ? " psa-slot-medium" : "";
      const estClass = ckt?.kvaEstimated ? " psa-slot-estimated" : "";
      const slotClasses = `${confClass}${estClass}`;
      const tooltip = ckt?.reviewNote ? `Review: ${ckt.reviewNote}` : "";

      const tdCkt = el("td", `psa-col-ckt${confClass}`, String(cktNum));
      tdCkt.dataset.ckt = String(cktNum);
      if (tooltip) tdCkt.title = tooltip;
      if (conf === "medium" || conf === "low") {
        tdCkt.appendChild(el("span", `psa-flag-dot ${conf}`));
      }

      const tdNote = el("td", `psa-col-note${slotClasses}`);
      const tdLoad = el("td", `psa-col-load${slotClasses}`);
      const tdPole = el("td", `psa-col-pole${slotClasses}`);
      const tdTrip = el("td", `psa-col-trip${slotClasses}`);
      const tdDesc = el("td", slotClasses.trim());
      const tdKva = el("td", `psa-col-kva${slotClasses}`);
      if (tooltip) tdDesc.title = tooltip;

      if (isContinuation) {
        tdNote.appendChild(el("div", "psa-cell-continuation", ckt.note || ""));
        tdLoad.appendChild(el("div", "psa-cell-continuation", ckt.loadType || ""));
        tdPole.appendChild(el("div", "psa-cell-continuation", "-"));
        tdTrip.appendChild(el("div", "psa-cell-continuation", "-"));
        tdDesc.appendChild(el("div", "psa-cell-continuation", "---"));

        const kvaInp = el("input", "psa-cell-input is-num psa-kva-input");
        kvaInp.type = "text";
        const val = ckt.phaseKva?.[offset];
        kvaInp.value = val !== null && val !== undefined ? String(val) : "";
        kvaInp.placeholder = "-";
        kvaInp.addEventListener("change", () => {
          if (!Array.isArray(ckt.phaseKva)) ckt.phaseKva = [];
          const parsed = parseNum(kvaInp.value);
          ckt.phaseKva[offset] = parsed;
          ckt.kvaEstimated = false;
          kvaInp.value = parsed !== null ? String(parsed) : "";
          renderLoadSummaryStrip(panel);
        });
        tdKva.appendChild(kvaInp);
      } else {
        const noteInp = el("input", "psa-cell-input is-num");
        noteInp.type = "text";
        noteInp.value = ckt?.note || "";
        noteInp.addEventListener("change", () => {
          const target = ensureCircuitAt(panel, cktNum);
          target.note = noteInp.value.trim().toUpperCase();
        });
        tdNote.appendChild(noteInp);

        const loadSel = el("select", "psa-cell-select");
        for (const code of LOAD_CODES) {
          const o = document.createElement("option");
          o.value = code;
          o.textContent = code || "—";
          if ((ckt?.loadType || "") === code) o.selected = true;
          loadSel.appendChild(o);
        }
        loadSel.addEventListener("change", () => {
          const target = ensureCircuitAt(panel, cktNum);
          target.loadType = loadSel.value;
          renderLoadSummaryStrip(panel);
        });
        tdLoad.appendChild(loadSel);

        const poleSel = el("select", "psa-cell-select");
        for (const pVal of [0, 1, 2, 3]) {
          const o = document.createElement("option");
          o.value = String(pVal);
          o.textContent = pVal === 0 ? "—" : String(pVal);
          const curP = ckt ? Number(ckt.poles ?? 1) : 0;
          if (curP === pVal) o.selected = true;
          poleSel.appendChild(o);
        }
        poleSel.addEventListener("change", () => {
          const target = ensureCircuitAt(panel, cktNum);
          const newPoles = Number(poleSel.value);
          target.poles = newPoles;
          if (!Array.isArray(target.phaseKva)) target.phaseKva = [];
          if (newPoles > target.phaseKva.length) {
            while (target.phaseKva.length < newPoles) target.phaseKva.push(null);
          } else if (newPoles > 0) {
            target.phaseKva = target.phaseKva.slice(0, newPoles);
          } else {
            target.phaseKva = [];
          }
          renderScheduleTable(panel);
          renderLoadSummaryStrip(panel);
        });
        tdPole.appendChild(poleSel);

        const tripInp = el("input", "psa-cell-input is-num");
        tripInp.type = "text";
        tripInp.value = ckt?.breakerAmps || "";
        tripInp.addEventListener("change", () => {
          const target = ensureCircuitAt(panel, cktNum);
          target.breakerAmps = tripInp.value.replace(/[^\d]/g, "");
          tripInp.value = target.breakerAmps;
        });
        tdTrip.appendChild(tripInp);

        const descInp = el("input", "psa-cell-input is-desc");
        descInp.type = "text";
        descInp.value = ckt?.description || "";
        descInp.addEventListener("change", () => {
          const target = ensureCircuitAt(panel, cktNum);
          target.description = descInp.value.trim().toUpperCase();
          descInp.value = target.description;
          if (target.confidence !== "high" && target.description) {
            target.confidence = "high";
            target.reviewNote = "";
            renderReviewPane();
          } else {
            renderLoadSummaryStrip(panel);
          }
        });
        tdDesc.appendChild(descInp);

        const kvaInp = el("input", "psa-cell-input is-num psa-kva-input");
        kvaInp.type = "text";
        const firstKva = ckt?.phaseKva?.[0];
        kvaInp.value = firstKva !== null && firstKva !== undefined ? String(firstKva) : "";
        kvaInp.addEventListener("change", () => {
          const target = ensureCircuitAt(panel, cktNum);
          if (!Array.isArray(target.phaseKva)) target.phaseKva = [];
          const parsed = parseNum(kvaInp.value);
          target.phaseKva[0] = parsed;
          target.kvaEstimated = false;
          kvaInp.value = parsed !== null ? String(parsed) : "";
          renderLoadSummaryStrip(panel);
        });
        tdKva.appendChild(kvaInp);
      }

      if (isLeft) {
        tr.append(tdCkt, tdNote, tdLoad, tdPole, tdTrip, tdDesc, tdKva);
      } else {
        tr.append(tdKva, tdDesc, tdPole, tdTrip, tdLoad, tdNote, tdCkt);
      }
    };

    for (let r = 0; r < rowsCount; r++) {
      const tr = document.createElement("tr");
      const oddCkt = r * 2 + 1;
      const evenCkt = r * 2 + 2;
      const phaseLetter = ["A", "B", "C"][r % 3];

      buildSideCells(tr, oddCkt, true);
      tr.appendChild(el("td", "psa-col-phase", phaseLetter));
      buildSideCells(tr, evenCkt, false);
      tbody.appendChild(tr);
    }
  }

  function renderLoadSummaryStrip(panel) {
    const strip = byId("psaLoadStrip");
    if (!strip) return;
    const summary = computePanelSummary(panel);
    strip.replaceChildren();

    const metrics = el("div", "psa-load-metrics");
    const addMetric = (label, value, warn = false) => {
      const m = el("div", `psa-metric${warn ? " is-warn" : ""}`);
      m.appendChild(el("span", "", label));
      m.appendChild(el("strong", "", value));
      metrics.appendChild(m);
    };

    addMetric("Ph A", `${summary.phaseA.toFixed(2)} kVA`);
    addMetric("Ph B", `${summary.phaseB.toFixed(2)} kVA`);
    if (Number(panel.phase) !== 1) addMetric("Ph C", `${summary.phaseC.toFixed(2)} kVA`);
    addMetric("Connected", `${summary.connectedTotalKva.toFixed(2)} kVA`);
    addMetric("NEC Demand", `${summary.demandTotalKva.toFixed(2)} kVA`);
    addMetric("Demand Amps", `${summary.demandAmps.toFixed(1)} A`);
    if (summary.connectedTotalKva > 0) {
      addMetric("Imbalance", `${summary.imbalancePct.toFixed(1)}%`, summary.imbalancePct > 10);
    }
    strip.appendChild(metrics);
    renderPanelAlertBar(panel, summary);
    renderPanelTabs();
  }

  function renderReviewPane() {
    const panel = getActivePanel();
    if (!panel) return;
    renderPanelTabs();
    renderPanelHeaderGrid(panel);
    renderScheduleTable(panel);
    renderLoadSummaryStrip(panel);
    renderViewerFilmstrip();
  }

  function renderFooterControls() {
    const sourcesActions = byId("psaSourcesFooterActions");
    const reviewActions = byId("psaReviewFooterActions");
    if (sourcesActions) sourcesActions.hidden = state.step !== "sources";
    if (reviewActions) reviewActions.hidden = state.step !== "review";

    const runBtn = byId("psaAnalyzeBtn");
    if (runBtn) {
      if (state.bgJob.running) {
        runBtn.disabled = true;
        runBtn.textContent = "Running in Background...";
      } else if (state.workflow === "field_photos") {
        const readyGroups = getReadyFieldGroups();
        const photoCount = readyGroups.reduce((acc, g) => acc + getGroupSources(g).length, 0);
        runBtn.disabled = state.busy || readyGroups.length === 0;
        runBtn.textContent = readyGroups.length
          ? `Extract ${readyGroups.length} Panel${readyGroups.length === 1 ? "" : "s"} (${photoCount} photo${photoCount === 1 ? "" : "s"})`
          : "Extract Panel Schedules";
      } else {
        const count = getSelectedDrawingSources().length;
        runBtn.disabled = state.busy || count === 0;
        runBtn.textContent = count
          ? `Extract from ${count} Drawing Sheet${count === 1 ? "" : "s"}`
          : "Extract Panel Schedules";
      }
    }

    const modeSel = byId("psaExportModeSelect");
    if (modeSel) modeSel.value = state.exportMode;
    const fmtSel = byId("psaExportFormatSelect");
    if (fmtSel) {
      fmtSel.value = state.exportFormat;
      fmtSel.hidden = state.exportMode !== "new";
    }
    const replaceWrap = byId("psaReplaceExistingWrap");
    if (replaceWrap) replaceWrap.hidden = state.exportMode !== "existing";
    const replaceCb = byId("psaReplaceExistingCb");
    if (replaceCb) replaceCb.checked = state.replaceExistingSheets;

    const pathBadge = byId("psaExportPathBadge");
    if (pathBadge) {
      pathBadge.textContent = state.exportPath || "Click Export or Browse to pick Excel file";
      pathBadge.title = state.exportPath || "";
    }

    const exportBtn = byId("psaExportBtn");
    if (exportBtn) {
      const includedCount = state.panels.filter((p) => p.includeInExport).length;
      exportBtn.disabled = state.busy || includedCount === 0;
      exportBtn.textContent = `Export ${includedCount} Panel${includedCount === 1 ? "" : "s"} to Excel`;
    }

    const openFileBtn = byId("psaOpenExcelBtn");
    const openFolderBtn = byId("psaOpenFolderBtn");
    if (openFileBtn) openFileBtn.hidden = !state.lastExportedPath;
    if (openFolderBtn) openFolderBtn.hidden = !state.lastExportedPath;
  }

  function renderAll() {
    renderHeader();
    renderBgProgressBanner();
    if (state.step === "sources") {
      renderSourcesView();
    } else {
      renderReviewPane();
    }
    renderFooterControls();
  }

  function jumpToNextFlag() {
    const panel = getActivePanel();
    if (!panel) return;
    const flagged = (panel.circuits || [])
      .filter((c) => c.confidence === "medium" || c.confidence === "low")
      .sort((a, b) => Number(a.circuitNumber) - Number(b.circuitNumber));
    if (!flagged.length) return;
    state.flagCursor = (state.flagCursor + 1) % flagged.length;
    const targetCkt = flagged[state.flagCursor].circuitNumber;
    const cell = document.querySelector(`#psaScheduleBody td[data-ckt="${targetCkt}"]`);
    if (cell) {
      for (const prev of document.querySelectorAll(".psa-slot-focus")) {
        prev.classList.remove("psa-slot-focus");
      }
      cell.classList.add("psa-slot-focus");
      cell.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  // ------------------------------------------------------------------
  // Fullscreen Image Lightbox & Interactive Cropper
  // ------------------------------------------------------------------

  function applyLightboxTransform() {
    const wrap = byId("psaLbCanvasWrap");
    if (!wrap) return;
    const lb = state.lightbox;
    wrap.style.transform =
      `translate3d(calc(-50% + ${lb.panX}px), calc(-50% + ${lb.panY}px), 0) ` +
      `scale(${lb.zoom}) rotate(${lb.rotation}deg)`;
    const lbl = byId("psaLbZoomLabel");
    if (lbl) lbl.textContent = `${Math.round(lb.zoom * 100)}%`;
  }

  function resetLightboxTransform() {
    const lb = state.lightbox;
    lb.zoom = 1;
    lb.panX = 0;
    lb.panY = 0;
    applyLightboxTransform();
  }

  function zoomLightboxTo(targetZoom, clientX = null, clientY = null) {
    const stage = byId("psaLbStage");
    const lb = state.lightbox;
    const oldZoom = lb.zoom || 1;
    const newZoom = Math.min(VIEWER_MAX_ZOOM, Math.max(VIEWER_MIN_ZOOM, targetZoom));
    if (Math.abs(newZoom - oldZoom) < 0.0005) return;

    if (stage && typeof clientX === "number" && typeof clientY === "number") {
      const rect = stage.getBoundingClientRect();
      const mx = clientX - (rect.left + rect.width / 2);
      const my = clientY - (rect.top + rect.height / 2);
      const ratio = newZoom / oldZoom;
      lb.panX = mx - (mx - lb.panX) * ratio;
      lb.panY = my - (my - lb.panY) * ratio;
    } else {
      const ratio = newZoom / oldZoom;
      lb.panX *= ratio;
      lb.panY *= ratio;
    }
    lb.zoom = newZoom;
    if (lb.zoom <= 1.001) {
      lb.panX = 0;
      lb.panY = 0;
    }
    applyLightboxTransform();
  }

  function renderLightboxCropBox() {
    const box = byId("psaLbCropBox");
    const sizeEl = byId("psaLbCropSize");
    const saveCopyBtn = byId("psaLbSaveCopyCropBtn");
    const replaceBtn = byId("psaLbReplaceCropBtn");
    const rect = state.lightbox.cropRect;
    const valid = Boolean(rect && rect.w > 0.01 && rect.h > 0.01);

    if (box) {
      box.hidden = !valid;
      if (valid) {
        box.style.left = `${(rect.x * 100).toFixed(3)}%`;
        box.style.top = `${(rect.y * 100).toFixed(3)}%`;
        box.style.width = `${(rect.w * 100).toFixed(3)}%`;
        box.style.height = `${(rect.h * 100).toFixed(3)}%`;
        if (sizeEl) {
          sizeEl.textContent = `${Math.round(rect.w * 100)}% × ${Math.round(rect.h * 100)}%`;
        }
      }
    }
    if (saveCopyBtn) saveCopyBtn.disabled = !valid || state.busy;
    if (replaceBtn) replaceBtn.disabled = !valid || state.busy;
  }

  function setLightboxCropMode(enabled) {
    const lb = state.lightbox;
    lb.cropMode = Boolean(enabled);
    lb.cropping = false;
    lb.cropStart = null;
    if (!lb.cropMode) lb.cropRect = null;

    const stage = byId("psaLbStage");
    const layer = byId("psaLbCropLayer");
    const bar = byId("psaLbCropBar");
    const toggleBtn = byId("psaLbCropToggleBtn");
    const sub = byId("psaLightboxSub");

    if (stage) stage.classList.toggle("is-crop-mode", lb.cropMode);
    if (layer) layer.hidden = !lb.cropMode;
    if (bar) bar.hidden = !lb.cropMode;
    if (toggleBtn) {
      toggleBtn.classList.toggle("is-crop-active", lb.cropMode);
      toggleBtn.textContent = lb.cropMode ? "Exit Crop" : "Crop Region";
    }
    if (sub) {
      sub.textContent = lb.cropMode
        ? "Drag a box over the image to crop (scroll wheel still zooms to cursor)"
        : "Scroll to zoom at cursor • Drag to pan • Double-click to toggle zoom";
    }
    renderLightboxCropBox();
  }

  function screenToLightboxImageNorm(clientX, clientY) {
    const wrap = byId("psaLbCanvasWrap");
    const img = byId("psaLbImg");
    const lb = state.lightbox;
    if (!wrap || !img) return null;
    const w0 = img.offsetWidth;
    const h0 = img.offsetHeight;
    if (w0 <= 0 || h0 <= 0) return null;

    const wrapRect = wrap.getBoundingClientRect();
    const cx = wrapRect.left + wrapRect.width / 2;
    const cy = wrapRect.top + wrapRect.height / 2;
    const sx = (clientX - cx) / (lb.zoom || 1);
    const sy = (clientY - cy) / (lb.zoom || 1);

    const rot = ((lb.rotation % 360) + 360) % 360;
    let lx = sx;
    let ly = sy;
    if (rot === 90) {
      lx = sy;
      ly = -sx;
    } else if (rot === 180) {
      lx = -sx;
      ly = -sy;
    } else if (rot === 270) {
      lx = -sy;
      ly = sx;
    }
    const ux = Math.max(0, Math.min(1, lx / w0 + 0.5));
    const uy = Math.max(0, Math.min(1, ly / h0 + 0.5));
    return { x: ux, y: uy };
  }

  async function openLightbox(source, context, startInCropMode = false) {
    if (!source) return;
    const overlay = byId("psaLightboxOverlay");
    const img = byId("psaLbImg");
    const titleEl = byId("psaLightboxTitle");
    const loading = byId("psaLbLoading");
    const destWrap = byId("psaLbDestWrap");
    const destSel = byId("psaLbDestBucket");
    if (!overlay || !img) return;

    const lb = state.lightbox;
    lb.open = true;
    lb.source = source;
    lb.context = context || null;
    lb.zoom = 1;
    lb.panX = 0;
    lb.panY = 0;
    lb.rotation = 0;
    lb.cropRect = null;

    if (titleEl) titleEl.textContent = source.pageLabel || source.name || "Image Preview";

    // Smart default destination bucket for "Save Crop as Copy"
    const isField = context?.workflow === "field_photos";
    if (destWrap) destWrap.hidden = !isField;
    if (isField && destSel) {
      // If cropping from Breakers/Directory/Ignored, default copy target to Nameplate/Tags
      const curBkt = context.bucket;
      destSel.value = curBkt === "nameplate" ? "nameplate" : "nameplate";
      if (curBkt === "main_breaker") destSel.value = "main_breaker";
    }

    overlay.hidden = false;
    setLightboxCropMode(Boolean(startInCropMode));
    applyLightboxTransform();

    if (source.viewerDataUrl) {
      if (loading) loading.hidden = true;
      img.src = source.viewerDataUrl;
      return;
    }

    img.src = source.thumbDataUrl || "";
    if (loading) loading.hidden = false;
    const bridge = api();
    if (bridge?.panel_studio_render_source) {
      try {
        const res = await bridge.panel_studio_render_source({
          kind: source.kind,
          path: source.path,
          pageIndex: source.pageIndex,
        });
        if (res?.status === "success" && res.viewerDataUrl) {
          source.viewerDataUrl = res.viewerDataUrl;
          if (state.lightbox.open && state.lightbox.source === source) {
            img.src = res.viewerDataUrl;
          }
        }
      } catch (err) {
        console.warn("Lightbox high-res render failed:", err);
      } finally {
        if (loading) loading.hidden = true;
      }
    } else if (loading) {
      loading.hidden = true;
    }
  }

  function closeLightbox() {
    const overlay = byId("psaLightboxOverlay");
    if (overlay) overlay.hidden = true;
    state.lightbox.open = false;
    state.lightbox.cropping = false;
    state.lightbox.dragging = false;
    state.lightbox.cropRect = null;
  }

  async function applyLightboxCrop(mode) {
    // mode: "copy" | "replace"
    const lb = state.lightbox;
    if (!lb.source || !lb.cropRect) return;
    const bridge = api();
    if (!bridge?.panel_studio_crop_source) {
      notify("Image crop backend is not ready.");
      return;
    }

    const ctx = lb.context || {};
    const destBucket =
      ctx.workflow === "field_photos"
        ? mode === "copy"
          ? byId("psaLbDestBucket")?.value || "nameplate"
          : ctx.bucket || "breakers"
        : "as_built_drawing";

    setBusy(true, "Cropping high-resolution image...", "Saving cropped image from original source...");
    try {
      const res = await bridge.panel_studio_crop_source({
        source: {
          kind: lb.source.kind,
          name: lb.source.name,
          path: lb.source.path,
          pageIndex: lb.source.pageIndex,
          pageLabel: lb.source.pageLabel,
          role: destBucket,
        },
        rect: lb.cropRect,
        rotation: lb.rotation,
        role: destBucket,
      });
      if (res?.status !== "success" || !res.item) {
        throw new Error(res?.message || "Could not crop image.");
      }

      const croppedItem = res.item;
      registerSourcesInIndex([croppedItem]);

      if (ctx.workflow === "field_photos") {
        const grp = state.fieldGroups.find((g) => g.id === ctx.groupId) || getActiveFieldGroup();
        if (grp) {
          if (mode === "replace") {
            const arr = ctx.bucket === "ignore" ? grp.ignored : grp.buckets[ctx.bucket];
            if (arr && ctx.index >= 0 && ctx.index < arr.length) {
              croppedItem.hint = arr[ctx.index].hint || "";
              arr[ctx.index] = croppedItem;
            }
          } else {
            const targetBucket = FIELD_BUCKETS.includes(destBucket) ? destBucket : "nameplate";
            croppedItem.role = targetBucket;
            grp.buckets[targetBucket].push(croppedItem);
          }
        }
      } else if (ctx.workflow === "as_built_drawing") {
        croppedItem.role = "as_built_drawing";
        if (mode === "replace" && ctx.index >= 0 && ctx.index < state.drawingSources.length) {
          state.drawingSources[ctx.index] = croppedItem;
        } else {
          state.drawingSources.push(croppedItem);
        }
      }

      closeLightbox();
      renderAll();
      const targetName =
        mode === "replace"
          ? "Replaced original image with cropped version."
          : ctx.workflow === "field_photos"
          ? `Saved cropped copy to ${ROLE_SHORT_LABELS[destBucket] || destBucket}.`
          : "Added cropped copy to drawing sheets.";
      setStatus(targetName, "success");
      notify(targetName, 3500);
    } catch (err) {
      setStatus(err?.message || "Image crop failed.", "error");
      notify(err?.message || "Image crop failed.");
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------------
  // Open / Close & Event Wiring
  // ------------------------------------------------------------------

  async function refreshStatus() {
    const bridge = api();
    if (!bridge?.panel_studio_get_status) return;
    try {
      const res = await bridge.panel_studio_get_status();
      if (res?.status === "success") {
        state.modelName = res.model || "gemini-4-hydrogen";
        state.hasApiKey = Boolean(res.hasApiKey);
        const pf = res.prefilter || null;
        const pfPill = byId("psaLocalModelStatus");
        if (pfPill && pf) {
          if (!pf.runtimeAvailable) {
            pfPill.textContent = "ONNX runtime missing";
          } else if (pf.customModelReady) {
            const acc = pf.customModelMetrics?.panelF1
              ? ` • ${Math.round(pf.customModelMetrics.panelF1 * 100)}% F1`
              : "";
            pfPill.textContent = `ACIES Trained Model (${pf.customModelSamples || 0} imgs${acc})`;
          } else if (pf.modelReady) {
            pfPill.textContent = "Local ONNX Zero-Shot ($0)";
          } else {
            pfPill.textContent = `1st run downloads ${pf.downloadSizeMb || 148} MB`;
          }
        }
        renderHeader();
      }
    } catch (err) {
      console.warn("Panel studio status check failed:", err);
    }
  }

  function setModalScrollLock(locked) {
    document.documentElement.classList.toggle("psa-modal-open", Boolean(locked));
    document.body.classList.toggle("psa-modal-open", Boolean(locked));
  }

  function openPanelScheduleStudio(launchContext = null) {
    if (launchContext) state.launchContext = launchContext;
    hideReadyToast();
    const dlg = byId("panelStudioDlg");
    if (!dlg) return;
    setModalScrollLock(true);
    if (!dlg.open) dlg.showModal();
    void refreshStatus();
    renderAll();
  }

  function closePanelScheduleStudio() {
    const dlg = byId("panelStudioDlg");
    if (dlg?.open) dlg.close();
    setModalScrollLock(false);
  }

  function findScrollableAncestor(target, stopAt) {
    let node = target instanceof Element ? target : null;
    while (node && node !== stopAt) {
      const style = window.getComputedStyle(node);
      const overflowY = style.overflowY;
      const overflowX = style.overflowX;
      const canScrollY =
        (overflowY === "auto" || overflowY === "scroll") &&
        node.scrollHeight > node.clientHeight + 1;
      const canScrollX =
        (overflowX === "auto" || overflowX === "scroll") &&
        node.scrollWidth > node.clientWidth + 1;
      if (canScrollY || canScrollX) return { node, canScrollY, canScrollX };
      node = node.parentElement;
    }
    return null;
  }

  function bindEvents() {
    const card = byId("toolPanelScheduleStudio");
    if (card) {
      const handler = () => openPanelScheduleStudio();
      card.addEventListener("click", handler);
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handler();
        }
      });
    }

    byId("psaCloseBtn")?.addEventListener("click", closePanelScheduleStudio);
    byId("psaMinimizeBtn")?.addEventListener("click", () => {
      closePanelScheduleStudio();
      notify("Panel Schedule AI Studio is running in the background — we will notify you when it is ready.", 4500);
    });
    byId("psaRemoveDupesBtn")?.addEventListener("click", removeDetectedDuplicates);
    byId("psaReadyToastOpenBtn")?.addEventListener("click", () => {
      hideReadyToast();
      openPanelScheduleStudio();
    });
    byId("psaReadyToastDismissBtn")?.addEventListener("click", hideReadyToast);
    const studioDlg = byId("panelStudioDlg");
    if (studioDlg) {
      studioDlg.addEventListener("close", () => setModalScrollLock(false));
      // Prevent any wheel scroll inside the modal (or on the backdrop) from scrolling the page behind it.
      studioDlg.addEventListener(
        "wheel",
        (e) => {
          if (e.target instanceof Element && e.target.closest("#psaViewerStage, #psaLbStage")) {
            return; // Viewer and Lightbox stages have dedicated preventDefault wheel handlers
          }
          const scrollable = findScrollableAncestor(e.target, studioDlg);
          if (!scrollable) {
            e.preventDefault();
            return;
          }
          const { node, canScrollY } = scrollable;
          if (!canScrollY) {
            if (Math.abs(e.deltaY) >= Math.abs(e.deltaX)) e.preventDefault();
            return;
          }
          const atTop = node.scrollTop <= 0 && e.deltaY < 0;
          const atBottom =
            node.scrollTop + node.clientHeight >= node.scrollHeight - 1 && e.deltaY > 0;
          if (atTop || atBottom) {
            e.preventDefault();
          }
        },
        { passive: false }
      );
    }
    byId("psaStepSourcesBtn")?.addEventListener("click", () => {
      state.step = "sources";
      renderAll();
    });
    byId("psaStepReviewBtn")?.addEventListener("click", () => {
      if (state.panels.length) {
        state.step = "review";
        renderAll();
      }
    });

    // Workflow switcher (Site Survey Photos vs As-Built Drawings)
    for (const tab of document.querySelectorAll(".psa-workflow-tab")) {
      tab.addEventListener("click", () => {
        state.workflow = tab.dataset.workflow === "as_built_drawing" ? "as_built_drawing" : "field_photos";
        renderAll();
      });
    }

    // Site Survey Panel Group management
    byId("psaAddFieldGroupBtn")?.addEventListener("click", () => {
      const grp = createFieldGroup(state.fieldGroups.length + 1);
      state.fieldGroups.push(grp);
      state.activeFieldGroupId = grp.id;
      renderFieldWorkflow();
      renderFooterControls();
    });

    byId("psaRemoveFieldGroupBtn")?.addEventListener("click", () => {
      if (state.fieldGroups.length <= 1) return;
      const idx = state.fieldGroups.findIndex((g) => g.id === state.activeFieldGroupId);
      if (idx >= 0) {
        state.fieldGroups.splice(idx, 1);
        state.activeFieldGroupId = state.fieldGroups[Math.max(0, idx - 1)].id;
        renderFieldWorkflow();
        renderFooterControls();
      }
    });

    byId("psaGroupPanelName")?.addEventListener("input", (e) => {
      const grp = getActiveFieldGroup();
      if (!grp) return;
      grp.panelName = e.target.value.toUpperCase();
      e.target.value = grp.panelName;
      renderFieldWorkflow();
    });

    byId("psaGroupCondition")?.addEventListener("change", (e) => {
      const grp = getActiveFieldGroup();
      if (!grp) return;
      grp.condition = e.target.value === "NEW" ? "NEW" : "EXISTING";
    });

    // Smart Survey Intake Bar (Local ONNX Pre-Filter + gemini-decision-1)
    byId("psaPrefilterFolderBtn")?.addEventListener("click", () => void scanSurveyFolderWithLocalPrefilter());
    byId("psaAutoSortBrowseBtn")?.addEventListener("click", () => void browseForAutoSort());
    byId("psaClearIgnoredBtn")?.addEventListener("click", () => {
      const grp = getActiveFieldGroup();
      if (!grp) return;
      grp.ignored = [];
      renderFieldWorkflow();
    });
    const autoSortBar = byId("psaAutoSortBar");
    if (autoSortBar) {
      autoSortBar.addEventListener("dragover", (e) => {
        e.preventDefault();
        autoSortBar.classList.add("is-dragover");
      });
      autoSortBar.addEventListener("dragleave", () => autoSortBar.classList.remove("is-dragover"));
      autoSortBar.addEventListener("drop", (e) => {
        e.preventDefault();
        autoSortBar.classList.remove("is-dragover");
        const files = e.dataTransfer?.files;
        if (files?.length) void autoSortBrowserFiles(files);
      });
    }

    // Structured 4 Photo Buckets + Ignored Tray (click, focus, browse, internal drag-move & external file drop)
    const handleBucketDrop = (e, targetBucket) => {
      e.preventDefault();
      // 1. Internal photo card drag-and-drop move between buckets
      let dragged = state.draggedPhoto;
      if (!dragged && e.dataTransfer) {
        const raw = e.dataTransfer.getData("application/x-psa-photo");
        if (raw) {
          try {
            dragged = JSON.parse(raw);
          } catch (_err) {
            dragged = null;
          }
        }
      }
      if (dragged) {
        state.draggedPhoto = null;
        const grp = state.fieldGroups.find((g) => g.id === dragged.groupId) || getActiveFieldGroup();
        if (grp) {
          // Resolve live index by itemId in case anything shifted
          const srcArr = dragged.fromBucket === "ignore" ? grp.ignored : grp.buckets[dragged.fromBucket];
          const liveIdx = srcArr ? srcArr.findIndex((it) => it.id === dragged.itemId) : dragged.index;
          if (liveIdx >= 0) {
            movePhotoBetweenBuckets(grp, dragged.fromBucket, liveIdx, targetBucket);
          }
        }
        return;
      }
      // 2. External file drop from OS Explorer
      if (targetBucket !== "ignore") {
        setActivePasteBucket(targetBucket);
        const files = e.dataTransfer?.files;
        if (files?.length) void addBrowserFilesToTarget(files, "field_photos", targetBucket);
      }
    };

    for (const bucketCard of document.querySelectorAll(".psa-bucket")) {
      const bucket = bucketCard.dataset.bucket;
      if (!bucket) continue;
      bucketCard.addEventListener("pointerdown", () => setActivePasteBucket(bucket));
      bucketCard.addEventListener("focusin", () => setActivePasteBucket(bucket));
      bucketCard.addEventListener("dragover", (e) => {
        e.preventDefault();
        if (e.dataTransfer && state.draggedPhoto) {
          e.dataTransfer.dropEffect = "move";
        }
        bucketCard.classList.add("is-dragover");
      });
      bucketCard.addEventListener("dragleave", (e) => {
        if (!bucketCard.contains(e.relatedTarget)) {
          bucketCard.classList.remove("is-dragover");
        }
      });
      bucketCard.addEventListener("drop", (e) => {
        bucketCard.classList.remove("is-dragover");
        handleBucketDrop(e, bucket);
      });
    }

    const ignoredTray = byId("psaIgnoredTray");
    if (ignoredTray) {
      ignoredTray.addEventListener("dragover", (e) => {
        if (!state.draggedPhoto) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
        ignoredTray.classList.add("is-dragover");
      });
      ignoredTray.addEventListener("dragleave", (e) => {
        if (!ignoredTray.contains(e.relatedTarget)) {
          ignoredTray.classList.remove("is-dragover");
        }
      });
      ignoredTray.addEventListener("drop", (e) => {
        ignoredTray.classList.remove("is-dragover");
        handleBucketDrop(e, "ignore");
      });
    }

    for (const browseBtn of document.querySelectorAll("[data-bucket-browse]")) {
      browseBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        void browseForTarget("field_photos", browseBtn.dataset.bucketBrowse);
      });
    }

    for (const dropArea of document.querySelectorAll("[data-bucket-drop]")) {
      const bucket = dropArea.dataset.bucketDrop;
      dropArea.addEventListener("click", () => void browseForTarget("field_photos", bucket));
      dropArea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          void browseForTarget("field_photos", bucket);
        }
      });
    }

    // As-Built Drawing dropzone & controls
    const drop = byId("psaDropzone");
    if (drop) {
      drop.addEventListener("click", () => void browseForTarget("as_built_drawing"));
      drop.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          void browseForTarget("as_built_drawing");
        }
      });
      drop.addEventListener("dragover", (e) => {
        e.preventDefault();
        drop.classList.add("is-dragover");
      });
      drop.addEventListener("dragleave", () => drop.classList.remove("is-dragover"));
      drop.addEventListener("drop", (e) => {
        e.preventDefault();
        drop.classList.remove("is-dragover");
        const files = e.dataTransfer?.files;
        if (files?.length) void addBrowserFilesToTarget(files, "as_built_drawing");
      });
    }

    byId("psaFallbackFileInput")?.addEventListener("change", (e) => {
      const files = e.target?.files;
      const target = state.pendingBrowseTarget || {
        workflow: state.workflow,
        bucket: state.activePasteBucket,
      };
      if (!files?.length) return;
      if (target.workflow === "auto_sort") {
        void autoSortBrowserFiles(files);
      } else {
        void addBrowserFilesToTarget(files, target.workflow, target.bucket);
      }
    });

    // Clipboard screenshot paste -> routes straight to active bucket (field mode) or drawings
    byId("panelStudioDlg")?.addEventListener("paste", (e) => {
      if (state.step !== "sources") return;
      const items = Array.from(e.clipboardData?.items || []);
      const imgFiles = items
        .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
        .map((it) => it.getAsFile())
        .filter(Boolean);
      if (imgFiles.length) {
        e.preventDefault();
        void addBrowserFilesToTarget(
          imgFiles,
          state.workflow,
          state.workflow === "field_photos" ? state.activePasteBucket : null
        );
      }
    });

    byId("psaAddFilesBtn")?.addEventListener("click", () => void browseForTarget("as_built_drawing"));
    byId("psaSelectAllBtn")?.addEventListener("click", () => {
      state.drawingSources.forEach((s) => (s.selected = true));
      renderDrawingWorkflow();
      renderFooterControls();
    });
    byId("psaSelectNoneBtn")?.addEventListener("click", () => {
      state.drawingSources.forEach((s) => (s.selected = false));
      renderDrawingWorkflow();
      renderFooterControls();
    });
    byId("psaClearSourcesBtn")?.addEventListener("click", () => {
      state.drawingSources = [];
      renderDrawingWorkflow();
      renderFooterControls();
    });

    byId("psaPanelNameHint")?.addEventListener("input", (e) => {
      state.drawingPanelNameHint = e.target.value;
    });

    byId("psaAnalyzeBtn")?.addEventListener("click", () => void runHydrogenAnalysis());

    // Viewer cursor-anchored zoom / pan / rotate / double-click
    byId("psaZoomInBtn")?.addEventListener("click", () => {
      zoomViewerTo(state.zoom * 1.35);
    });
    byId("psaZoomOutBtn")?.addEventListener("click", () => {
      zoomViewerTo(state.zoom / 1.35);
    });
    byId("psaZoomFitBtn")?.addEventListener("click", resetViewerTransform);
    byId("psaZoomActualBtn")?.addEventListener("click", () => {
      zoomViewerTo(2.5);
    });
    byId("psaRotateBtn")?.addEventListener("click", () => {
      state.rotation = (state.rotation + 90) % 360;
      clampViewerPan();
      applyViewerTransform();
    });

    const stage = byId("psaViewerStage");
    if (stage) {
      stage.addEventListener(
        "wheel",
        (e) => {
          e.preventDefault();
          e.stopPropagation();
          let dy = e.deltaY;
          if (e.deltaMode === 1) dy *= 32;
          else if (e.deltaMode === 2) dy *= 240;
          const clampedDelta = Math.max(-220, Math.min(220, dy));
          const sensitivity = e.ctrlKey ? 0.006 : 0.0022;
          const factor = Math.exp(-clampedDelta * sensitivity);
          zoomViewerTo(state.zoom * factor, e.clientX, e.clientY);
        },
        { passive: false }
      );
      stage.addEventListener("dblclick", (e) => {
        e.preventDefault();
        if (state.zoom <= 1.15) {
          zoomViewerTo(2.5, e.clientX, e.clientY);
        } else {
          resetViewerTransform();
        }
      });
      stage.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        state.dragging = true;
        state.dragStartX = e.clientX - state.panX;
        state.dragStartY = e.clientY - state.panY;
        stage.classList.add("is-dragging");
        stage.setPointerCapture?.(e.pointerId);
      });
      stage.addEventListener("pointermove", (e) => {
        if (!state.dragging) return;
        state.panX = e.clientX - state.dragStartX;
        state.panY = e.clientY - state.dragStartY;
        clampViewerPan();
        applyViewerTransform();
      });
      const endDrag = () => {
        state.dragging = false;
        stage.classList.remove("is-dragging");
      };
      stage.addEventListener("pointerup", endDrag);
      stage.addEventListener("pointercancel", endDrag);
    }

    // Draggable split-pane divider between Source Viewer and Schedule Editor
    const resizer = byId("psaReviewResizer");
    const reviewView = byId("psaReviewView");
    if (resizer && reviewView) {
      let resizing = false;
      resizer.addEventListener("pointerdown", (e) => {
        resizing = true;
        resizer.classList.add("is-resizing");
        resizer.setPointerCapture?.(e.pointerId);
      });
      resizer.addEventListener("pointermove", (e) => {
        if (!resizing) return;
        const rect = reviewView.getBoundingClientRect();
        if (rect.width <= 0) return;
        const pct = ((e.clientX - rect.left) / rect.width) * 100;
        const clamped = Math.max(25, Math.min(70, pct));
        reviewView.style.setProperty("--psa-viewer-width", `${clamped.toFixed(1)}%`);
        clampViewerPan();
        applyViewerTransform();
      });
      const stopResize = () => {
        resizing = false;
        resizer.classList.remove("is-resizing");
      };
      resizer.addEventListener("pointerup", stopResize);
      resizer.addEventListener("pointercancel", stopResize);
    }

    // Panel tab management in Step 2
    byId("psaAddBlankPanelBtn")?.addEventListener("click", () => {
      const nextNum = state.panels.length + 1;
      const blank = createBlankPanel(`P${nextNum}`);
      state.panels.push(blank);
      state.activePanelId = blank.id;
      renderReviewPane();
      renderFooterControls();
    });

    byId("psaDeletePanelBtn")?.addEventListener("click", () => {
      if (state.panels.length <= 1) return;
      const idx = state.panels.findIndex((p) => p.id === state.activePanelId);
      if (idx >= 0) {
        state.panels.splice(idx, 1);
        state.activePanelId = state.panels[Math.max(0, idx - 1)]?.id || "";
        renderReviewPane();
        renderFooterControls();
        void selectViewerSource(0);
      }
    });

    // Export controls
    byId("psaExportModeSelect")?.addEventListener("change", (e) => {
      state.exportMode = e.target.value === "existing" ? "existing" : "new";
      state.exportPath = "";
      state.lastExportedPath = "";
      renderFooterControls();
    });
    byId("psaExportFormatSelect")?.addEventListener("change", (e) => {
      state.exportFormat = e.target.value === "xls" ? "xls" : "xlsx";
      if (state.exportPath) {
        state.exportPath = state.exportPath.replace(/\.(xlsx|xls)$/i, `.${state.exportFormat}`);
      }
      renderFooterControls();
    });
    byId("psaReplaceExistingCb")?.addEventListener("change", (e) => {
      state.replaceExistingSheets = Boolean(e.target.checked);
    });
    byId("psaBrowseExportBtn")?.addEventListener("click", () => void chooseExportPath());
    byId("psaExportBtn")?.addEventListener("click", () => void runExcelExport());
    byId("psaCheckupCancelBtn")?.addEventListener("click", hideExportFlagCheckup);
    byId("psaCheckupReviewBtn")?.addEventListener("click", () => {
      const firstId = byId("psaFlagCheckOverlay")?.dataset.firstFlaggedPanelId;
      if (firstId) {
        jumpToPanelFlags(firstId);
      } else {
        hideExportFlagCheckup();
      }
    });
    byId("psaCheckupContinueBtn")?.addEventListener("click", () => {
      void runExcelExport({ skipFlagCheckup: true });
    });
    byId("psaOpenExcelBtn")?.addEventListener("click", () => void openExportedPath(false));
    byId("psaOpenFolderBtn")?.addEventListener("click", () => void openExportedPath(true));

    // Fullscreen Lightbox & Cropper events
    byId("psaLbCloseBtn")?.addEventListener("click", closeLightbox);
    byId("psaLbZoomInBtn")?.addEventListener("click", () => zoomLightboxTo(state.lightbox.zoom * 1.35));
    byId("psaLbZoomOutBtn")?.addEventListener("click", () => zoomLightboxTo(state.lightbox.zoom / 1.35));
    byId("psaLbFitBtn")?.addEventListener("click", resetLightboxTransform);
    byId("psaLbRotateBtn")?.addEventListener("click", () => {
      state.lightbox.rotation = (state.lightbox.rotation + 90) % 360;
      state.lightbox.cropRect = null;
      applyLightboxTransform();
      renderLightboxCropBox();
    });
    byId("psaLbCropToggleBtn")?.addEventListener("click", () => {
      setLightboxCropMode(!state.lightbox.cropMode);
    });
    byId("psaLbClearCropBtn")?.addEventListener("click", () => {
      state.lightbox.cropRect = null;
      renderLightboxCropBox();
    });
    byId("psaLbSaveCopyCropBtn")?.addEventListener("click", () => void applyLightboxCrop("copy"));
    byId("psaLbReplaceCropBtn")?.addEventListener("click", () => void applyLightboxCrop("replace"));

    const lbStage = byId("psaLbStage");
    if (lbStage) {
      lbStage.addEventListener(
        "wheel",
        (e) => {
          e.preventDefault();
          e.stopPropagation();
          let dy = e.deltaY;
          if (e.deltaMode === 1) dy *= 32;
          else if (e.deltaMode === 2) dy *= 240;
          const clampedDelta = Math.max(-220, Math.min(220, dy));
          const sensitivity = e.ctrlKey ? 0.006 : 0.0022;
          zoomLightboxTo(state.lightbox.zoom * Math.exp(-clampedDelta * sensitivity), e.clientX, e.clientY);
        },
        { passive: false }
      );

      lbStage.addEventListener("dblclick", (e) => {
        if (state.lightbox.cropMode) return;
        e.preventDefault();
        if (state.lightbox.zoom <= 1.15) {
          zoomLightboxTo(2.5, e.clientX, e.clientY);
        } else {
          resetLightboxTransform();
        }
      });

      lbStage.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        const lb = state.lightbox;
        if (lb.cropMode) {
          const pt = screenToLightboxImageNorm(e.clientX, e.clientY);
          if (!pt) return;
          lb.cropping = true;
          lb.cropStart = pt;
          lb.cropRect = { x: pt.x, y: pt.y, w: 0, h: 0 };
          lbStage.setPointerCapture?.(e.pointerId);
          renderLightboxCropBox();
          return;
        }
        lb.dragging = true;
        lb.dragStartX = e.clientX - lb.panX;
        lb.dragStartY = e.clientY - lb.panY;
        lbStage.classList.add("is-dragging");
        lbStage.setPointerCapture?.(e.pointerId);
      });

      lbStage.addEventListener("pointermove", (e) => {
        const lb = state.lightbox;
        if (lb.cropping && lb.cropStart) {
          const pt = screenToLightboxImageNorm(e.clientX, e.clientY);
          if (!pt) return;
          const x1 = Math.min(lb.cropStart.x, pt.x);
          const y1 = Math.min(lb.cropStart.y, pt.y);
          const x2 = Math.max(lb.cropStart.x, pt.x);
          const y2 = Math.max(lb.cropStart.y, pt.y);
          lb.cropRect = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
          renderLightboxCropBox();
          return;
        }
        if (!lb.dragging) return;
        lb.panX = e.clientX - lb.dragStartX;
        lb.panY = e.clientY - lb.dragStartY;
        applyLightboxTransform();
      });

      const endLbPointer = () => {
        state.lightbox.cropping = false;
        state.lightbox.dragging = false;
        lbStage.classList.remove("is-dragging");
      };
      lbStage.addEventListener("pointerup", endLbPointer);
      lbStage.addEventListener("pointercancel", endLbPointer);
    }

    // Intercept Escape so closing Lightbox or Checkup doesn't dismiss the entire Studio dialog
    byId("panelStudioDlg")?.addEventListener("cancel", (e) => {
      if (state.lightbox.open) {
        e.preventDefault();
        closeLightbox();
        return;
      }
      const checkup = byId("psaFlagCheckOverlay");
      if (checkup && !checkup.hidden) {
        e.preventDefault();
        hideExportFlagCheckup();
      }
    });
  }

  function initialize() {
    hideReadyToast();
    bindEvents();
    renderAll();
    window.openPanelScheduleStudio = openPanelScheduleStudio;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
