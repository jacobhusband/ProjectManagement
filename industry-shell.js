// Industry presentation layer for the rest of the shell: Pages, Tools and
// Timesheets.
//
// Turn 2 of the "Deliverables UI" design. industry-projects.js redraws the
// Projects tab; this file gives the other three screens the same grammar —
// numbered spec bands, hairline plates, one steel accent, and a ledger whose
// only filled field is today.
//
// Like the projects layer, nothing here owns data. It wraps the renderers
// script.js already has and decorates what they produce, so every handler
// (page open/delete, tool launch, plugin install, hour entry) keeps working
// untouched. Loaded after script.js and industry-projects.js.

// ---------------------------------------------------------------------------
// Wrapping helper
// ---------------------------------------------------------------------------

// script.js calls its renderers as bare globals, so replacing the global
// binding is enough to interpose — no call sites need editing.
function industryWrap(name, wrapper) {
  const original = window[name];
  if (typeof original !== "function") return false;
  if (original.__industryWrapped) return true;
  const wrapped = function (...args) {
    return wrapper.call(this, original.bind(this), ...args);
  };
  wrapped.__industryWrapped = true;
  wrapped.__industryOriginal = original;
  window[name] = wrapped;
  return true;
}

const INDUSTRY_DAY_ORDER = Object.freeze([
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
  "sun",
]);

const INDUSTRY_WEEKEND_DAYS = Object.freeze(["sat", "sun"]);

// Indexed by Date#getDay(): 0 is Sunday.
const INDUSTRY_WEEKDAY_KEYS = Object.freeze([
  "sun",
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
]);

function industryKick(text, extraClass = "") {
  return el("span", {
    className: `reg-kick ${extraClass}`.trim(),
    textContent: text,
  });
}

function industryRule() {
  return el("div", { className: "ind-band-rule" });
}

// "3d ago", "2w ago", "2mo ago" — the meta line on a page card.
function industryAgo(isoString) {
  const then = new Date(isoString);
  if (isNaN(then)) return "";
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 7) return `${days}d ago`;
  if (days < 31) return `${Math.floor(days / 7)}w ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

// ---------------------------------------------------------------------------
// PAGES — reference notes as index cards
// ---------------------------------------------------------------------------

// The card ordinal, reset at the top of every list render so the numbers read
// 01, 02, 03 down the grid.
let industryPageOrdinal = 0;

// The design gives each card a section kicker. The page record carries no
// taxonomy, so the kicker states what the page actually is — a written page or
// a canvas — rather than inventing a category for it.
function industryPageKind(page) {
  return isCanvasPage(page?.page) ? "Canvas" : "Page";
}

function decorateGlobalPageCard(card, page) {
  if (!card || card.dataset.industryReady === "true") return card;
  card.dataset.industryReady = "true";

  industryPageOrdinal += 1;
  const head = el("div", { className: "pg-head" }, [
    industryKick(industryPageKind(page), "pg-kind"),
    industryKick(String(industryPageOrdinal).padStart(2, "0"), "pg-no"),
  ]);
  card.insertBefore(head, card.firstChild);

  // The mockup also stamps an author on the meta rule; page records don't
  // store one, so the rule carries only the edit time we actually know.
  const edited = industryAgo(page?.page?.updatedAt);
  const meta = el("div", { className: "pg-meta" }, [
    industryKick(edited ? `Edited ${edited}` : "Not yet edited"),
    el("div", { className: "pg-meta-spacer" }),
  ]);
  const del = card.querySelector(".tab-delete-icon");
  if (del) card.insertBefore(meta, del);
  else card.appendChild(meta);

  return card;
}

// The count reads as a kicker beside the title, the way the register states
// its total.
function updateGlobalPagesCount() {
  const header = document.querySelector("#notes-panel .global-pages-header");
  if (!header) return;
  const total = Array.isArray(globalPages) ? globalPages.length : 0;
  let countEl = header.querySelector(".global-pages-count");
  if (!countEl) {
    countEl = industryKick("", "global-pages-count");
    const title = header.querySelector(".section-title");
    if (title) title.after(countEl);
    else header.insertBefore(countEl, header.firstChild);
  }
  countEl.textContent = total
    ? `${industryPlural(total, "reference note")}`
    : "No reference notes yet";
}

function installPagesIndustryLayer() {
  industryWrap("createGlobalPageCard", (original, page, searchQuery) =>
    decorateGlobalPageCard(original(page, searchQuery), page)
  );
  industryWrap("renderGlobalPagesView", (original) => {
    industryPageOrdinal = 0;
    const result = original();
    updateGlobalPagesCount();
    return result;
  });
}

// ---------------------------------------------------------------------------
// TOOLS — a parts catalog
// ---------------------------------------------------------------------------

// Short spec captions, the way a parts list states a part's kind rather than
// repeating its description. The full description stays on the help mark's
// tooltip, which script.js already builds from .tool-card-body.
const INDUSTRY_TOOL_CAPTIONS = Object.freeze({
  toolCleanDrawings: "Headless cleanup",
  toolPublishDwgs: "Plot + combine",
  toolManageLayers: "Layer states",
  toolRepairXrefPaths: "Batch, per project",
  toolCleanXrefs: "Attach / detach",
  toolBackupDrawings: "On delivery",
  toolCreateNarrativeTemplate: "DOCX",
  toolCreatePlanCheckTemplate: "DOCX",
  toolLightingSchedule: "Preview",
  toolTitle24Compliance: "Preview",
});

function decorateToolCard(card) {
  if (!card || card.dataset.industryReady === "true") return;
  const info = card.querySelector(".tool-card-info");
  if (!info) return; // script.js has not built the wrappers yet
  card.dataset.industryReady = "true";

  const caption = INDUSTRY_TOOL_CAPTIONS[card.id];
  if (caption && !info.querySelector(".tl-caption")) {
    info.appendChild(el("div", { className: "tl-caption", textContent: caption }));
  }

  // Every tool in the catalogue carries a mark. A card with no drawn icon gets
  // the monogram the design uses in its place, so the column still lines up.
  if (!card.querySelector(".tool-icon")) {
    const name = info.querySelector(".tool-card-header")?.textContent || "";
    const monogram = name
      .split(/[^A-Za-z0-9]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0].toUpperCase())
      .join("");
    const content = card.querySelector(".tool-card-content") || card;
    content.insertBefore(
      el("div", { className: "tool-icon tl-monogram", textContent: monogram }),
      content.firstChild
    );
  }
}

// Each group heading becomes a numbered band: 01 GENERAL ————— 6
function decorateToolsSection(section, index) {
  // The plugin band heads itself with .commands-header rather than the
  // .tools-section-header the other bands use.
  const header = section.querySelector(".tools-section-header, .commands-header");
  if (!header || header.dataset.industryReady === "true") return;
  header.classList.add("tools-section-header");
  header.dataset.industryReady = "true";

  header.insertBefore(
    el("span", {
      className: "ind-band-no",
      textContent: String(index + 1).padStart(2, "0"),
    }),
    header.firstChild
  );

  const title = header.querySelector(".tools-section-title");
  const rule = industryRule();
  const count = industryKick("", "tools-section-count");
  if (title) title.after(rule, count);
  else header.append(rule, count);

  // The warning banner belongs to the caution plate below, not the band.
  const banner = header.querySelector(".tools-warning-banner");
  if (banner) section.appendChild(banner);
}

// The band's count is restated after every render, because the plugin band
// grows as bundles load.
function updateToolsSectionCounts() {
  document.querySelectorAll("#tools-panel .tools-section").forEach((section) => {
    const count = section.querySelector(".tools-section-count");
    if (!count) return;
    if (section.querySelector("#commands-container")) {
      const rows = section.querySelectorAll(".tl-plugin-row:not(.tl-plugin-head)");
      const updates = section.querySelectorAll(".tl-plugin-avail.is-new");
      count.textContent = updates.length
        ? `${rows.length} · ${industryPlural(updates.length, "update")} available`
        : String(rows.length);
      return;
    }
    count.textContent = String(section.querySelectorAll(".tool-card").length);
  });
}

// The preview band is drawn as a caution plate: a hatched rail, the note, then
// the dashed cells.
function buildUnderConstructionPlate() {
  const section = document.querySelector(
    "#tools-panel .tools-section-under-construction"
  );
  if (!section || section.dataset.industryPlateReady === "true") return;
  const grid = section.querySelector(".tools-grid");
  if (!grid) return;
  section.dataset.industryPlateReady = "true";

  const banner = section.querySelector(".tools-warning-banner");
  const main = el("div", { className: "tools-uc-main" });
  if (banner) main.appendChild(banner);
  main.appendChild(grid);

  const body = el("div", { className: "tools-uc-body" }, [
    el("div", { className: "tools-uc-rail hatch" }),
    main,
  ]);
  section.appendChild(body);
}

function decorateToolsPanel() {
  const sections = [...document.querySelectorAll("#tools-panel .tools-section")];
  sections.forEach((section, index) => decorateToolsSection(section, index));
  document
    .querySelectorAll("#tools-panel .tool-card")
    .forEach((card) => decorateToolCard(card));
  buildUnderConstructionPlate();
  updateToolsSectionCounts();
}

// --- 04 AutoCAD plugins: the release cards become a ruled version table -----

// The design states each plugin's installed and available versions instead of
// showing a column of identical Update buttons. The action button and its help
// mark are the nodes script.js built, moved rather than rebuilt, so the
// delegated install/update/uninstall handler keeps working.
function buildPluginTable(bundles) {
  const container = document.getElementById("commands-container");
  if (!container) return;
  const cards = [...container.querySelectorAll(".release-card")];
  if (!cards.length) return;

  const byName = new Map();
  (Array.isArray(bundles) ? bundles : []).forEach((bundle) => {
    if (bundle?.bundle_name) byName.set(String(bundle.bundle_name), bundle);
  });

  const head = el("div", { className: "tl-plugin-row tl-plugin-head" }, [
    industryKick("Plugin"),
    industryKick("Installed"),
    industryKick("Available"),
    industryKick("Action", "tl-plugin-action-head"),
  ]);

  const rows = cards.map((card) => {
    const button = card.querySelector(".release-card-footer .btn");
    const help = card.querySelector(".tool-card-help");
    const status = card.querySelector(".bundle-status");
    const nameText =
      card.querySelector(".release-card-title span")?.textContent?.trim() || "";
    const bundle = byName.get(String(button?.dataset.bundleName || ""));

    const name = el("div", { className: "tl-plugin-name" });
    if (status) name.appendChild(status);
    name.appendChild(el("span", { textContent: nameText, title: nameText }));

    const installed = el("div", {
      className: "reg-val tl-plugin-installed",
      textContent: bundle?.local_version ? String(bundle.local_version) : "—",
    });

    const hasUpdate = bundle?.state === "update_available";
    const availText = hasUpdate
      ? String(bundle.remote_version)
      : bundle?.state === "installed"
        ? "up to date"
        : bundle?.remote_version
          ? String(bundle.remote_version)
          : "—";
    const available = el("div", {
      className: `reg-val tl-plugin-avail ${hasUpdate ? "is-new" : "is-current"}`,
      textContent: availText,
    });

    const action = el("div", { className: "tl-plugin-action" });
    if (button) action.appendChild(button);
    if (help) action.appendChild(help);

    return el("div", { className: "tl-plugin-row" }, [
      name,
      installed,
      available,
      action,
    ]);
  });

  container.innerHTML = "";
  container.append(head, ...rows);
}

function installToolsIndustryLayer() {
  industryWrap("renderBundles", async function (original, bundles) {
    const result = await original(bundles);
    buildPluginTable(bundles);
    decorateToolsPanel();
    return result;
  });
  industryWrap("initToolCardDetailsToggles", (original) => {
    const result = original();
    decorateToolsPanel();
    return result;
  });
}

// ---------------------------------------------------------------------------
// TIMESHEETS — a ruled ledger
// ---------------------------------------------------------------------------

// Which weekday column is "today" — only when the sheet is showing the week
// that contains today, so an old week is never drawn as if it were live.
function industryTodayDayKey() {
  const week = currentTimesheetWeek;
  if (!(week instanceof Date) || isNaN(week)) return "";
  const start = new Date(week);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 7);
  const today = industryToday();
  if (today < start || today >= end) return "";
  // The hour columns are keyed by weekday name, and the stored week may start
  // on either Sunday or Monday, so the mark is read off the day itself rather
  // than off its offset from the start of the week.
  return INDUSTRY_WEEKDAY_KEYS[today.getDay()] || "";
}

// The day columns sit at a fixed offset in both the header and each row, so
// the header, the hour cells and the totals row can be marked from one map.
function industryMarkDayColumns() {
  const table = document.querySelector("#timesheets-panel .timesheet-table");
  if (!table) return;
  const todayKey = industryTodayDayKey();

  const headCells = [...table.querySelectorAll("thead th")];
  const firstDayIndex = headCells.findIndex((th) =>
    th.classList.contains("ts-day-col")
  );
  if (firstDayIndex === -1) return;

  INDUSTRY_DAY_ORDER.forEach((day, offset) => {
    const isWeekend = INDUSTRY_WEEKEND_DAYS.includes(day);
    const isToday = day === todayKey;

    const th = headCells[firstDayIndex + offset];
    if (th) {
      th.classList.toggle("is-weekend", isWeekend && !isToday);
      th.classList.toggle("is-today", isToday);
    }

    table.querySelectorAll("tbody tr.ts-entry-row").forEach((row) => {
      const cell = row.querySelectorAll("td.ts-hour-cell")[offset];
      if (!cell) return;
      cell.classList.toggle("is-weekend", isWeekend && !isToday);
      cell.classList.toggle("is-today", isToday);
    });

    const totalCell = document.getElementById(
      `total${day.charAt(0).toUpperCase()}${day.slice(1)}`
    );
    if (totalCell) {
      totalCell.classList.toggle("is-weekend", isWeekend && !isToday);
      totalCell.classList.toggle("is-today", isToday);
      const value = Number.parseFloat(totalCell.textContent);
      totalCell.classList.toggle("is-empty", !Number.isFinite(value) || value <= 0);
    }
  });
}

// "Week 37 · JH" beside the stepper — the sheet says whose week it is.
function updateTimesheetWeekKicker() {
  const toolbar = document.querySelector("#timesheets-panel .panel-toolbar");
  if (!toolbar) return;
  // The stepper plate holds only ‹ week ›; "Today" and the week's identity
  // line stand beside it, as separate controls on the board.
  const selector = toolbar.querySelector(".timesheets-week-selector");
  const todayBtn = document.getElementById("currentWeekBtn");
  if (selector && todayBtn && todayBtn.parentElement === selector) {
    selector.after(todayBtn);
  }
  let kick = toolbar.querySelector(".ts-week-kick");
  if (!kick) {
    kick = industryKick("", "ts-week-kick");
    if (todayBtn) todayBtn.after(kick);
    else if (selector) selector.after(kick);
    else toolbar.appendChild(kick);
  }
  const week = currentTimesheetWeek;
  const parts = [];
  if (week instanceof Date && !isNaN(week)) {
    const jan1 = new Date(week.getFullYear(), 0, 1);
    parts.push(`Week ${Math.ceil(((week - jan1) / 86400000 + jan1.getDay() + 1) / 7)}`);
  }
  const initials = getDefaultPmInitials();
  if (initials) parts.push(initials);
  kick.textContent = parts.join(" · ");
}

// --- the due-projects tray -------------------------------------------------

// The design states the day rather than a bare date, so adding an entry is a
// one-glance decision.
function industryDueDayLabel(text) {
  const date = parseDueStr(text);
  if (!date) return "";
  // "Tue 09/08" — the day carries the meaning, the year is noise in a tray
  // that only ever shows this week and next.
  return date
    .toLocaleDateString(undefined, {
      weekday: "short",
      month: "2-digit",
      day: "2-digit",
    })
    .replace(",", "");
}

function decorateSuggestionCard(card, dueText) {
  const due = card.querySelector(".ts-suggestion-due");
  if (due && dueText) {
    const label = industryDueDayLabel(dueText);
    if (label) due.textContent = label;
  }
  // Work due inside the week on screen is drawn on the accent.
  const date = parseDueStr(dueText);
  if (date instanceof Date && !isNaN(date) && currentTimesheetWeek instanceof Date) {
    const end = new Date(currentTimesheetWeek);
    end.setDate(end.getDate() + 7);
    if (date < end) card.classList.add("is-due-soon");
  }
  return card;
}

// The tray heading gets the register's rule-and-count band.
function updateSuggestionsTrayHead() {
  const section = document.querySelector("#timesheets-panel .timesheet-suggestions");
  if (!section) return;
  const title = section.querySelector(".section-title");
  const hint = section.querySelector("p.tiny.muted");
  const list = document.getElementById("timesheetSuggestions");
  if (!title) return;

  let head = section.querySelector(".ts-tray-head");
  if (!head) {
    head = el("div", { className: "ts-tray-head" });
    title.before(head);
    head.appendChild(title);
    if (hint) {
      hint.className = "reg-kick";
      head.appendChild(hint);
    }
    head.appendChild(industryRule());
    head.appendChild(industryKick("", "ts-tray-count"));
  }
  const count = head.querySelector(".ts-tray-count");
  if (count && list) {
    count.textContent = String(list.querySelectorAll(".ts-suggestion-card").length);
  }
}

function installTimesheetsIndustryLayer() {
  industryWrap("createSuggestionCard", (original, project, names, dueDate, status) =>
    decorateSuggestionCard(original(project, names, dueDate, status), dueDate)
  );
  // The standing meeting states its cadence rather than repeating its name.
  industryWrap("createWeeklyMeetingCard", (original) => {
    const card = original();
    const sub = card?.querySelector(".ts-suggestion-deliverable");
    if (sub) sub.textContent = "Recurring · Mon";
    return card;
  });
  industryWrap("renderTimesheetSuggestions", (original) => {
    const result = original();
    updateSuggestionsTrayHead();
    return result;
  });
  industryWrap("renderTimesheets", (original) => {
    const result = original();
    updateTimesheetWeekKicker();
    industryMarkDayColumns();
    return result;
  });
  // Totals are restated on every keystroke, so the ledger's marks follow them.
  industryWrap("updateTimesheetTotals", (original, entries) => {
    const result = original(entries);
    industryMarkDayColumns();
    return result;
  });
  industryWrap("renderTimesheetEntries", (original, entries) => {
    const result = original(entries);
    industryMarkDayColumns();
    return result;
  });
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

function installShellIndustryLayer() {
  installPagesIndustryLayer();
  installToolsIndustryLayer();
  installTimesheetsIndustryLayer();
  decorateToolsPanel();
  installModernWorkspaceMenus();
  installModernWorkspaceDialogs();
}

// Move the original controls, retaining their IDs, handlers and live state.
// Native disclosures preserve Tab/Enter/Space behavior without pretending
// the existing column editor is an ARIA menu of simple menuitems.
function installModernWorkspaceMenus() {
  if (document.getElementById("boardOptionsMenu")) return;
  const heading = document.querySelector("#projects-panel .projects-board-heading");
  if (heading && !heading.querySelector(".projects-header-actions")) {
    const actions = el("div", { className: "toolbar-actions projects-header-actions", role: "group", "aria-label": "Project actions" });
    for (const [id, label] of [["quickNew", "New project"], ["statsBtn", "Statistics"], ["projectsWidthToggle", "Wide layout"]]) {
      const button = document.getElementById(id);
      if (!button) continue;
      button.classList.add("projects-header-action");
      button.appendChild(el("span", { textContent: label }));
      actions.appendChild(button);
    }
    heading.appendChild(actions);
  }
  const menus = [];
  function group(id, label, anchor, controls) {
    if (!anchor) return;
    const details = el("details", { id, className: "modern-action-menu" });
    const summary = el("summary", { "aria-label": label, title: label });
    const cog = document.querySelector("#settingsBtn svg")?.cloneNode(true);
    if (cog) {
      cog.setAttribute("aria-hidden", "true");
      summary.appendChild(cog);
    } else summary.textContent = "⚙";
    const panel = el("div", { className: "modern-menu-panel" });
    details.append(summary, panel);
    anchor.before(details);
    for (const [controlId, text] of controls) {
      const button = document.getElementById(controlId);
      if (!button) continue;
      button.appendChild(el("span", { className: "modern-menu-label", textContent: text }));
      panel.appendChild(button);
    }
    details.addEventListener("toggle", () => {
      if (details.open) {
        menus.forEach(other => { if (other !== details) other.open = false; });
        positionPanel();
      }
      else closeColumnConfigMenu();
    });
    function positionPanel() {
      if (!details.open) return;
      panel.style.transform = "";
      const bounds = panel.getBoundingClientRect();
      const shift = bounds.left < 16 ? 16 - bounds.left
        : bounds.right > window.innerWidth - 16 ? window.innerWidth - 16 - bounds.right : 0;
      panel.style.transform = `translateX(${shift}px)`;
    }
    window.addEventListener("resize", positionPanel);
    panel.addEventListener("click", event => {
      const button = event.target.closest("button");
      if (!button || button.closest("#columnConfigMenu") || button.id === "columnConfigBtn" || button.hasAttribute("aria-pressed")) return;
      // Close before an existing handler opens a modal or changes focus.
      details.open = false;
    }, true);
    details.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      details.open = false;
      closeColumnConfigMenu();
      summary.focus();
    });
    menus.push(details);
    return panel;
  }
  const panel = group("boardOptionsMenu", "Board settings", document.getElementById("projectsEmptyColumnsToggle"), [
    ["projectsEmptyColumnsToggle", "Minimize empty columns"],
    ["projectsHideEmptyColumnsToggle", "Hide empty columns"],
    ["columnConfigBtn", "Configure columns"],
  ]);
  const columns = document.getElementById("columnConfigMenu");
  if (panel && columns) {
    columns.classList.add("modern-board-option");
    panel.appendChild(columns);
  }
  document.addEventListener("click", event => {
    menus.forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  }, true);
  document.querySelectorAll(".main-tab-btn, .view-toggle-btn").forEach(button => {
    button.addEventListener("click", () => menus.forEach(menu => { menu.open = false; }));
  });

  // Activity stays above the command dock, even when its action sheet expands.
  const dock = document.querySelector(".cmd-dock");
  if (dock && typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(() => {
      document.documentElement.style.setProperty("--modern-command-height", `${dock.getBoundingClientRect().height}px`);
    });
    observer.observe(dock);
  }
}

// Reparent the existing fields so their handlers, values and autosave survive
// navigation. Related sections share a page, with their original headings intact.
function installModernWorkspaceDialogs() {
  const dialog = document.getElementById("settingsDlg");
  const body = dialog?.querySelector(".modal-body");
  if (!body || dialog.querySelector(".settings-navigation")) return;
  const nav = el("nav", { className: "settings-navigation", "aria-label": "Settings sections" });
  const content = el("div", { className: "settings-content" });
  const sections = [];
  const pageTitles = new Map([
    ["general", "General"],
    ["tools", "Tools"],
    ["account", "Account & Sync"],
    ["timesheets", "Timesheets"],
    ["maintenance", "Maintenance"],
  ]);
  const pages = new Map();
  function createPage(key, title) {
    const section = el("section", { className: "settings-page", id: `settings-page-${key}`, hidden: true });
    const heading = el("h2", { className: "settings-page-title", id: `${section.id}-title`, textContent: title });
    section.setAttribute("aria-labelledby", heading.id);
    section.appendChild(heading);
    const button = el("button", {
      type: "button", textContent: title, "aria-controls": section.id, "aria-pressed": "false",
    });
    button.addEventListener("click", () => {
      sections.forEach(entry => {
        entry.section.hidden = entry.section !== section;
        entry.button.setAttribute("aria-pressed", String(entry.button === button));
      });
      content.scrollTop = 0;
    });
    sections.push({ section, button });
    pages.set(key, section);
    nav.appendChild(button);
    content.appendChild(section);
    return section;
  }
  pageTitles.forEach((title, key) => createPage(key, title));
  let subsection;
  let subsectionCount = 0;
  for (const node of Array.from(body.children)) {
    if (node.matches(".section-title, .danger-zone")) {
      const title = node.matches(".danger-zone") ? "Danger Zone" : node.textContent.trim();
      // Unassigned future sections still get a page instead of disappearing.
      const key = node.dataset.settingsPage || `extra-${subsectionCount}`;
      const section = pages.get(key) || createPage(key, title);
      subsection = el("section", { className: "settings-subsection" });
      const heading = node.matches(".danger-zone") ? node.querySelector("h3") : node;
      if (heading) {
        heading.id = `settings-subsection-${subsectionCount}-title`;
        subsection.setAttribute("aria-labelledby", heading.id);
      }
      subsectionCount++;
      section.appendChild(subsection);
    }
    // The autosave notice moves to the persistent footer below.
    if (node.matches("p.tiny.muted") && node.textContent.includes("Settings are saved automatically")) {
      node.remove();
    } else if (subsection) subsection.appendChild(node);
  }
  body.classList.remove("stack");
  body.classList.add("settings-layout");
  body.append(nav, content);
  const footer = el("div", { className: "workspace-dialog-footer" });
  footer.appendChild(el("span", { textContent: "Changes save automatically", className: "muted" }));
  const done = el("button", { type: "button", className: "btn workspace-dialog-done", textContent: "Done" });
  done.addEventListener("click", () => dialog.close());
  footer.appendChild(done);
  dialog.appendChild(footer);
  sections[0]?.button.click();
  const scratchpad = document.getElementById("scratchpadPanel");
  if (scratchpad) {
    const footer = el("div", { className: "scratchpad-footer" });
    footer.appendChild(el("span", { textContent: "Unsorted notes" }));
    const status = document.getElementById("scratchpadStatus");
    if (status) footer.appendChild(status);
    scratchpad.appendChild(footer);
  }
}

document.addEventListener("DOMContentLoaded", installShellIndustryLayer);
