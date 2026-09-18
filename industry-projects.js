// Industry presentation layer for the Projects tab.
//
// Implements the "Deliverables UI" design: the register row (list view), the
// deliverable plate (board view), one global command line docked to the bottom
// of the application.
//
// Everything here reads the same project + deliverable records script.js owns
// and calls back into its existing handlers (status changes, calendar picker,
// tool launches, notes, folders) so behaviour stays identical — only the
// presentation changes. Loaded after script.js.

const INDUSTRY_STATUS_OPTIONS = Object.freeze([
  "In progress",
  "Waiting",
  "On hold",
  "Pending Review",
  "Complete",
  "Completed (by others)",
  "Delivered",
]);




// ---------------------------------------------------------------------------
// Date + state helpers
// ---------------------------------------------------------------------------

function industryToday() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return today;
}

function industryDayDiff(date) {
  if (!(date instanceof Date) || isNaN(date)) return null;
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  return Math.round((target - industryToday()) / 86400000);
}

function industryPlural(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function industryRelativeDays(days) {
  if (days === null || days === undefined) return "";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  // Countdowns drop the "in": the stamp reads "2 days", not "in 2 days".
  if (days > 0) return industryPlural(days, "day");
  return `${industryPlural(-days, "day")} late`;
}

function getDeliverablePrimaryStatus(deliverable) {
  return STATUS_PRIORITY.find((status) => hasStatus(deliverable, status)) || "In progress";
}

function getProjectClientLabel(project) {
  const parts = [];
  const account = extractAccountFromPath(project?.path);
  if (account) parts.push(account);
  const nick = String(project?.nick || "").trim();
  if (nick && nick !== account) parts.push(nick);
  return parts.join(" · ");
}

function getProjectShortName(project) {
  const nick = String(project?.nick || "").trim();
  if (nick) return nick;
  const name = String(project?.name || "").trim();
  if (!name) return String(project?.id || "").trim();
  const first = name.split(",")[0].trim();
  return first.length > 28 ? `${first.slice(0, 27)}…` : first;
}

// One read of a deliverable that every Industry surface shares:
//   kind  — late | open | done
//   rail  — hatch | dashed | accent | muted   (the left rail / bar treatment)
//   stamp — the status object drawn in the Status column
function getDeliverableRegisterState(deliverable) {
  const finished = isFinished(deliverable);
  const status = getDeliverablePrimaryStatus(deliverable);
  const externalDate = parseDueStr(getHardDueStr(deliverable));
  const effectiveDate = parseDueStr(getEffectiveDueStr(deliverable));
  const externalDays = externalDate ? industryDayDiff(externalDate) : null;
  const effectiveDays = effectiveDate ? industryDayDiff(effectiveDate) : null;

  if (finished) {
    return {
      kind: "done",
      rail: "muted",
      status,
      stamp: { text: status || "Complete", style: "neutral" },
      sub: "",
      daysLate: 0,
      daysAhead: effectiveDays,
      externalLate: false,
    };
  }

  const externalLate = externalDays !== null && externalDays < 0;
  const internalLate = effectiveDays !== null && effectiveDays < 0;
  if (externalLate || internalLate) {
    const daysLate = externalLate ? -externalDays : -effectiveDays;
    return {
      kind: "late",
      rail: "hatch",
      status,
      stamp: {
        text: `${daysLate} ${daysLate === 1 ? "DAY" : "DAYS"} LATE`,
        style: "solid",
      },
      sub: status,
      daysLate,
      daysAhead: effectiveDays,
      externalLate,
    };
  }

  const relative = effectiveDays === null ? "" : industryRelativeDays(effectiveDays);

  return {
    kind: "open",
    rail: "accent",
    status,
    stamp: { text: status, style: "tag" },
    sub: effectiveDays === null ? "no date set" : relative,
    daysLate: 0,
    daysAhead: effectiveDays,
    externalLate: false,
  };
}

function getAllProjectDeliverableRows() {
  const rows = [];
  (Array.isArray(db) ? db : []).forEach((project) => {
    const deliverables =
      typeof getOverviewDeliverables === "function"
        ? getOverviewDeliverables(project)
        : Array.isArray(project?.deliverables)
          ? project.deliverables
          : [];
    deliverables.forEach((deliverable) => {
      if (!deliverable) return;
      rows.push({ project, deliverable });
    });
  });
  return rows;
}

// Clicks on controls inside a row must not count as "select this row".
function isInteractiveTarget(target) {
  return !!target?.closest?.(
    "button, a, input, textarea, select, [role='button'], [contenteditable='true']"
  );
}

// ---------------------------------------------------------------------------
// Shared pieces: stamps, date fields, action stamps
// ---------------------------------------------------------------------------

function getRegisterStampText(state) {
  return String(state?.stamp?.text || "").trim();
}

// Returns null when there is nothing worth stamping; callers skip the cell.
function createRegisterStamp(state, deliverable, project, { text, dateField } = {}) {
  const label = String(text ?? getRegisterStampText(state)).trim();
  if (!label) return null;
  const dateLabel = dateField === "hardDue" ? "External" : "Internal";
  const dateValue = dateField === "hardDue" ? getHardDueStr(deliverable) : deliverable?.due;
  const tooltip = dateField
    ? `${dateLabel} date ${humanDate(dateValue)}. Click to change.`
    : "Select this deliverable and choose a status in the command line";
  const stamp = el("button", {
    type: "button",
    className: `reg-stamp reg-stamp--${state.stamp.style}`,
    textContent: label,
    title: tooltip,
    "aria-label": dateField ? tooltip : `Status: ${label}. Select to change status.`,
  });
  stamp.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (dateField) {
      showCalendarForDeliverableBadge(stamp, deliverable, project, dateField);
    } else {
      selectDeliverableForCommands(deliverable, project, { expand: true, focus: "status" });
    }
  });
  return stamp;
}

function createRegisterDateField(deliverable, project, field, state) {
  const value =
    field === "hardDue"
      ? getHardDueStr(deliverable)
      : String(deliverable?.due || "").trim();
  const label = field === "hardDue" ? "External" : "Internal";
  const wrap = el("div", {
    className: `reg-field reg-field--${field === "hardDue" ? "external" : "internal"}${
      value ? "" : " is-blank"
    }`,
    role: "button",
    tabIndex: 0,
    title: value
      ? `${label} date ${humanDate(value)}. Click to change.`
      : `Set the ${label.toLowerCase()} date.`,
    "aria-label": value ? `${label} date ${humanDate(value)}` : `Set the ${label.toLowerCase()} date`,
  });
  // No label and no "not set": the column header says which date this is, and
  // an unset date reads as an empty cell.
  const val = el("div", {
    className: `reg-val${value ? "" : " is-empty"}`,
    textContent: value ? humanDate(value) : "—",
  });
  if (field === "hardDue" && value) {
    wrap.classList.add("is-external");
    if (state.kind === "late" && state.externalLate) wrap.classList.add("is-late");
  }
  const open = (event) => {
    event.preventDefault();
    event.stopPropagation();
    showCalendarForDeliverableBadge(wrap, deliverable, project, field);
  };
  wrap.addEventListener("click", open);
  wrap.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") open(event);
  });
  wrap.append(val);
  const date = value ? parseDueStr(value) : null;
  const days = date ? industryDayDiff(date) : null;
  if (field === "hardDue" && days !== null && !isFinished(deliverable) && days <= 0) {
    wrap.appendChild(el("span", {
      className: `reg-date-context${days < 0 ? " is-late" : ""}`,
      textContent: days === 0 ? "Due today" : industryRelativeDays(days),
    }));
  }
  return wrap;
}

function createRegisterIco({ text, title, className = "", onClick }) {
  const button = el("button", {
    type: "button",
    className: `reg-ico ${className}`.trim(),
    textContent: text,
    title,
    "aria-label": title,
  });
  button.draggable = false;
  button.addEventListener("dragstart", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const result = onClick?.(event);
    if (result && typeof result.catch === "function") {
      result.catch((error) => console.warn("Deliverable action failed:", error));
    }
  });
  return button;
}

// Notes stay in one button; the corner badge counts important project notes.
function addImportantNotesBadge(button, project) {
  const count = getProjectImportantItems(project).length;
  button.classList.add("notes-badge-host");
  if (!count) return;
  button.classList.add("has-count");
  const label = `${button.title}. ${industryPlural(count, "important note")}`;
  button.title = label;
  button.setAttribute("aria-label", label);
  button.appendChild(el("span", {
    className: "notes-important-badge",
    textContent: String(count),
    "aria-hidden": "true",
  }));
}

function createRegisterActions(deliverable, project) {
  const wrap = el("div", { className: "reg-actions" });
  if (!project) return wrap;
  const noteCount = getProjectImportantItems(project).length;
  const notes = createRegisterIco({
    text: String(noteCount),
    className: noteCount ? "has-count" : "",
    title: noteCount
      ? `${industryPlural(noteCount, "important note")} — open project notes`
      : "Open project notes",
    onClick: () => openProjectPage(project),
  });
  notes.prepend(createIcon("M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z", 15));
  wrap.appendChild(notes);
  return wrap;
}

function attachDeliverableRename(nameEl, deliverable) {
  nameEl.title = "Double-click to rename";
  nameEl.addEventListener("dblclick", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const input = el("input", {
      className: "reg-code-input",
      type: "text",
      value: deliverable.name || "",
    });
    nameEl.hidden = true;
    nameEl.parentNode.insertBefore(input, nameEl.nextSibling);
    input.focus();
    input.select();
    let finished = false;
    const finish = async (shouldSave) => {
      if (finished) return;
      finished = true;
      const next = input.value.trim();
      if (shouldSave && next && next !== deliverable.name) {
        deliverable.name = next;
        nameEl.textContent = next;
        await save();
      }
      input.remove();
      nameEl.hidden = false;
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        finish(true);
      } else if (e.key === "Escape") {
        e.preventDefault();
        finish(false);
      }
    });
    input.addEventListener("blur", () => finish(true));
    input.addEventListener("click", (e) => e.stopPropagation());
  });
}

// ---------------------------------------------------------------------------
// 1a — Register row (list view)
// ---------------------------------------------------------------------------

function buildDeliverableRegisterColumns(deliverable, project) {
  syncDeliverableWorkItemFields(deliverable);
  if (!deliverable.id) deliverable.id = createId("dlv");
  const state = getDeliverableRegisterState(deliverable);

  const code = el("div", {
    className: "reg-code",
    textContent: deliverable.name || "Deliverable",
  });
  attachDeliverableRename(code, deliverable);

  const internal = createRegisterDateField(deliverable, project, "due", state);
  const external = createRegisterDateField(deliverable, project, "hardDue", state);

  // Deadline warnings live beside dates; status always shows workflow state.
  const statusCol = el("div", { className: "reg-status" });
  const workflowState = { ...state, stamp: { text: state.status, style: "tag" } };
  const stamp = createRegisterStamp(workflowState, deliverable, project);
  if (stamp) {
    stamp.dataset.status = LABEL_TO_KEY[state.status] || "inProgress";
    statusCol.appendChild(stamp);
  }

  const actions = createRegisterActions(deliverable, project);
  return [code, internal, external, statusCol, actions];
}

function renderDeliverableRegisterCell(cell, deliverable, project) {
  if (!cell) return;
  cell.innerHTML = "";
  cell.classList.add("reg-cell");
  if (!deliverable) {
    cell.appendChild(el("div", { className: "reg-code is-empty", textContent: "—" }));
    return;
  }
  buildDeliverableRegisterColumns(deliverable, project).forEach((node) =>
    cell.appendChild(node)
  );
}

// Grouped-by-project mode stacks every visible deliverable of a project in
// one row; each becomes its own five-column line under the shared project.
function renderDeliverableRegisterCellGroup(cell, deliverables, project, note = "") {
  if (!cell) return;
  cell.innerHTML = "";
  cell.classList.add("reg-cell", "reg-cell--multi");
  const stack = el("div", { className: "reg-multi" });
  if (note) {
    stack.appendChild(el("div", { className: "reg-note", textContent: note }));
  }
  if (!deliverables.length) {
    stack.appendChild(el("div", { className: "reg-code is-empty", textContent: "—" }));
  }
  deliverables.forEach((deliverable) => {
    const line = el("div", {
      className: `reg-line reg-line--${getDeliverableRegisterState(deliverable).kind}`,
      tabIndex: 0,
    });
    line.dataset.deliverableId = String(deliverable.id || "");
    buildDeliverableRegisterColumns(deliverable, project).forEach((node) =>
      line.appendChild(node)
    );
    attachDeliverableSelection(line, deliverable, project);
    stack.appendChild(line);
  });
  cell.appendChild(stack);
}

// Clicking (or pressing Enter on) a row makes it the target of the command line.
function attachDeliverableSelection(element, deliverable, project) {
  element.addEventListener("click", (event) => {
    if (isInteractiveTarget(event.target)) return;
    if (window.getSelection?.()?.toString()) return;
    selectDeliverableForCommands(deliverable, project);
  });
  element.addEventListener("keydown", (event) => {
    if (event.target !== element) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectDeliverableForCommands(deliverable, project, { expand: true });
    }
  });
}

// Turns the plain table row script.js builds into a register row: adds the
// rail, moves the account/nick under the project name, marks the state.
function decorateProjectRegisterRow(tr, project, deliverable) {
  if (!tr) return;
  const state = deliverable ? getDeliverableRegisterState(deliverable) : null;
  tr.classList.add("reg-row");
  if (state) tr.classList.add(`reg-row--${state.kind}`);
  if (deliverable && isDeliverablePinned(deliverable)) tr.classList.add("is-pinned");
  if (deliverable?.id) tr.dataset.deliverableId = String(deliverable.id);

  const idCell = tr.querySelector(".cell-id");
  if (idCell && !idCell.querySelector(".reg-rail")) {
    idCell.insertBefore(
      el("span", { className: `reg-rail reg-rail--${state?.rail || "muted"}` }),
      idCell.firstChild
    );
  }

  const main = tr.querySelector(".project-details-main");
  if (main) {
    const smalls = [...main.querySelectorAll("small.muted")];
    const clientText = smalls
      .map((node) => node.textContent.replace(/^\s*\(|\)\s*$/g, "").trim())
      .filter(Boolean)
      .join(" · ");
    smalls.forEach((node) => node.remove());
    main.querySelector(".path-link, .project-title-text")?.classList.add("reg-pname");
    const meta = el("div", { className: "reg-client" });
    const idBadge = idCell?.querySelector(".id-badge");
    if (idBadge) meta.appendChild(idBadge);
    if (clientText) meta.appendChild(el("span", { textContent: `${idBadge ? " · " : ""}${clientText}` }));
    main.appendChild(meta);
  }

  if (deliverable && !groupDeliverablesByProject) {
    tr.tabIndex = 0;
    attachDeliverableSelection(tr, deliverable, project);
  }
}

// Numbers each section divider ("Pinned — 01") and fills the footer count.
function finalizeProjectsRegister(tbody, pagination) {
  if (!tbody) return;
  const registerRows = [...tbody.children];
  registerRows.forEach((row, rowIndex) => {
    if (!row.classList.contains("week-separator-row")) return;
    const separator = row.querySelector(".week-separator");
    if (!separator) return;
    let count = separator.querySelector(".reg-sep-count");
    if (!count) {
      count = el("span", { className: "reg-sep-count" });
      separator.appendChild(count);
    }
    let sectionCount = 0;
    for (let i = rowIndex + 1; i < registerRows.length; i += 1) {
      if (registerRows[i].classList.contains("week-separator-row")) break;
      if (registerRows[i].classList.contains("reg-row")) sectionCount += 1;
    }
    count.textContent = String(sectionCount);
  });

  const footer = document.getElementById("registerFooterCount");
  if (footer) {
    const shown = Array.isArray(pagination?.items) ? pagination.items.length : 0;
    const total = getAllProjectDeliverableRows().length;
    footer.textContent = `${shown} of ${total} shown`;
  }
  syncCommandDockSelection();
}

// ---------------------------------------------------------------------------
// 1b — Deliverable plate (board view)
// ---------------------------------------------------------------------------

function createBlueprintCorners() {
  return ["tl", "tr", "bl", "br"].map((pos) => el("i", { className: `corner ${pos}` }));
}

function createPlateRuleCell(label, value, { muted = false, filled = false, strong = false, hatched = false, onClick = null, title = "" } = {}) {
  const cell = el("div", {
    className: `plate-rule-cell${filled ? " is-filled" : ""}${hatched ? " is-hatched" : ""}`,
  });
  cell.append(
    el("div", { className: "reg-kick", textContent: label }),
    el("div", {
      className: `reg-val${muted ? " is-empty" : ""}${strong ? " is-strong" : ""}`,
      textContent: value,
    })
  );
  if (onClick) {
    cell.classList.add("is-clickable");
    cell.setAttribute("role", "button");
    cell.tabIndex = 0;
    if (title) cell.title = title;
    cell.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      onClick(event);
    });
    cell.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onClick(event);
      }
    });
  }
  return cell;
}

// Foot button: opens the project folder; right-click still offers the
// server/local/edit/delete menu the project name used to carry.
function createPlateFolderButton(project) {
  const button = el("button", {
    type: "button",
    className: "reg-ico plate-folder",
    title: "Open project folder",
    "aria-label": "Open project folder",
  });
  const path = String(project?.path || "").trim();
  if (path) {
    button.title = `Open: ${path}`;
    button.setAttribute("aria-label", `Open project folder ${path}`);
  }
  button.innerHTML =
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">' +
    '<path d="M1.75 12.75V3.25h4.1l1.4 1.7h7v7.8z" fill="none" stroke="currentColor" ' +
    'stroke-width="1.3" stroke-linejoin="round" /></svg>';
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    void openProjectPathFolder(project);
  });
  attachProjectDirectoryContextMenu(button, project);
  return button;
}

function renderDeliverablePlateCard(deliverable, project) {
  syncDeliverableWorkItemFields(deliverable);
  const deliverableId = String(deliverable?.id || createId("dlv")).trim();
  if (!deliverable.id) deliverable.id = deliverableId;
  const state = getDeliverableRegisterState(deliverable);

  const card = el("div", {
    className: `deliverable-card-new plate-card blueprint plate-card--${state.kind}${
      isDeliverablePinned(deliverable) ? " is-pinned-deliverable" : ""
    }`,
    tabIndex: 0,
  });
  card.dataset.deliverableId = deliverableId;
  createBlueprintCorners().forEach((corner) => card.appendChild(corner));

  // Head: project id · client / deliverable title / stamp
  const head = el("div", { className: "plate-head" });
  const identity = el("div", { className: "plate-identity" });
  const kickParts = [String(project?.id || "").trim(), getProjectClientLabel(project)].filter(Boolean);
  identity.appendChild(el("div", { className: "reg-kick plate-kick", textContent: kickParts.join(" · ") || "—" }));
  const title = el("div", { className: "plate-title", textContent: deliverable.name || "Deliverable" });
  attachDeliverableRename(title, deliverable);
  identity.appendChild(title);
  // The card has no column header, so the stamp carries the countdown when the
  // deliverable has a date; otherwise the status, and nothing when neither.
  const countdown =
    state.kind === "late" || state.kind === "done" || state.daysAhead === null
      ? ""
      : industryRelativeDays(state.daysAhead);
  const stamp = createRegisterStamp(state, deliverable, project, {
    text: countdown || getRegisterStampText(state),
    dateField: countdown || state.kind === "late"
      ? state.externalLate || !String(deliverable?.due || "").trim() ? "hardDue" : "due"
      : undefined,
  });
  head.appendChild(identity);
  if (stamp) head.appendChild(stamp);
  card.appendChild(head);

  // Project name (label only — the folder button in the foot opens the folder)
  const projectName = String(project?.name || "").trim();
  if (projectName) {
    const nameEl = el("div", { className: "plate-project", textContent: projectName, title: projectName });
    attachProjectDirectoryContextMenu(nameEl, project);
    card.appendChild(nameEl);
  }

  // Milestone rule: internal → external → delivered
  const rule = el("div", { className: "plate-rule" });
  const internalValue = String(deliverable?.due || "").trim();
  const externalValue = getHardDueStr(deliverable);
  rule.appendChild(
    createPlateRuleCell("Internal", internalValue ? humanDate(internalValue) : "", {
      muted: !internalValue,
      title: "Click to change the internal date",
      onClick: (event) => {
        showCalendarForDeliverableBadge(event.currentTarget, deliverable, project, "due");
      },
    })
  );
  rule.appendChild(
    createPlateRuleCell("External", externalValue ? humanDate(externalValue) : "", {
      muted: !externalValue,
      strong: !!externalValue && state.kind !== "done",
      hatched: state.kind === "late" && state.externalLate,
      title: "Click to change the external date",
      onClick: (event) => {
        showCalendarForDeliverableBadge(event.currentTarget, deliverable, project, "hardDue");
      },
    })
  );
  rule.appendChild(
    createPlateRuleCell("Delivered", state.kind === "done" ? state.status || "Complete" : "", {
      muted: state.kind !== "done",
      filled: state.kind === "done",
    })
  );
  card.appendChild(rule);

  // Foot
  const foot = el("div", { className: "plate-foot" });
  if (project) foot.appendChild(createPlateFolderButton(project));
  foot.appendChild(el("span", { className: "plate-spacer" }));
  if (project) {
    const noteCount = getProjectImportantItems(project).length;
    const notes = el("button", {
      type: "button",
      className: "plate-notes reg-kick",
      textContent: industryPlural(noteCount, "note"),
      title: noteCount
        ? `${industryPlural(noteCount, "important note")} — open project notes`
        : "Open project notes",
    });
    notes.addEventListener("click", (event) => {
      event.stopPropagation();
      openProjectPage(project);
    });
    notes.prepend(createIcon("M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z", 15));
    foot.appendChild(notes);
  }
  card.appendChild(foot);

  attachDeliverableSelection(card, deliverable, project);
  return card;
}

// ---------------------------------------------------------------------------
// 1c — Command dock: one command line for the whole application
// ---------------------------------------------------------------------------
//
// Works in either order: type an action and then pick a deliverable, or pick a
// deliverable and then type. The line also searches: projects first, then the
// chosen project's deliverables, then commands. The action list stays
// collapsed under the line until the user expands it.

let industryCommandDock = null;

function ensureCommandDock() {
  if (industryCommandDock) return industryCommandDock;

  const root = el("div", {
    className: "cmd-dock",
    id: "commandDock",
    role: "region",
    "aria-label": "Command line",
  });
  root.dataset.expanded = "false";

  // Expandable action list (above the line)
  const body = el("div", { className: "cmd-dock-body" });
  body.hidden = true;
  const columns = el("div", { className: "cmd-body" });
  const left = el("div", { className: "cmd-col cmd-col--left" });
  const right = el("div", { className: "cmd-col cmd-col--right" });
  columns.append(left, right);
  const promptView = el("div", { className: "cmd-prompt-view" });
  promptView.hidden = true;
  const foot = el("div", { className: "cmd-foot" });
  const scope = el("span", { className: "reg-kick cmd-scope" });
  const footShortcuts = el("span", {
    className: "reg-kick cmd-shortcuts",
    textContent: "←→ ↑↓ move · ↩ run · # find a project · esc clear / collapse",
  });
  foot.append(
    footShortcuts,
    el("span", { className: "cmd-spacer" }),
    scope
  );
  body.append(columns, promptView, foot);

  // The line itself
  const bar = el("div", { className: "cmd-dock-bar" });
  const context = el("button", {
    type: "button",
    className: "reg-kick cmd-context",
    title: "Selected deliverable — click to clear",
  });
  const input = el("input", {
    type: "text",
    className: "cmd-search",
    placeholder: "Type a command…",
    "aria-label": "Command line",
    autocomplete: "off",
    spellcheck: false,
  });
  const pending = el("span", { className: "reg-kick cmd-pending" });
  pending.hidden = true;
  const hint = el("span", { className: "reg-kick cmd-key", textContent: "Ctrl K" });
  const expand = el("button", {
    type: "button",
    className: "cmd-expand",
    "aria-expanded": "false",
    title: "Show available actions",
  });
  expand.append(
    el("span", { className: "reg-kick", textContent: "Actions" }),
    el("span", { className: "cmd-expand-chevron", "aria-hidden": "true", textContent: "▴" })
  );
  bar.append(context, input, pending, hint, expand);

  root.append(body, bar);
  document.body.appendChild(root);

  industryCommandDock = {
    root,
    body,
    columns,
    promptView,
    foot,
    footShortcuts,
    left,
    right,
    scope,
    context,
    input,
    pending,
    expand,
    deliverable: null,
    project: null,
    pendingKey: null,
    pendingLabel: "",
    items: [],
    sections: [],
    activeIndex: -1,
    expanded: false,
  };

  input.addEventListener("input", () => {
    if (industryActivePrompt) {
      handleCommandDockPromptInput();
      return;
    }
    if (input.value.trim() && !industryCommandDock.expanded) setCommandDockExpanded(true);
    filterCommandDock();
  });
  input.addEventListener("keydown", handleCommandDockKeydown);
  // Capture before outside controls run: explicit status/action triggers can
  // still reopen the sheet, while ordinary outside clicks simply dismiss it.
  document.addEventListener("pointerdown", (event) => {
    if (industryCommandDock.expanded && !root.contains(event.target)) {
      if (industryActivePrompt) return;
      setCommandDockExpanded(false);
    }
  }, true);
  body.addEventListener("keydown", (event) => {
    if (event.target !== input) handleCommandDockKeydown(event);
  });
  expand.addEventListener("click", () => {
    setCommandDockExpanded(!industryCommandDock.expanded);
    if (industryCommandDock.expanded) input.focus({ preventScroll: true });
  });
  context.addEventListener("click", () => {
    if (industryActivePrompt) {
      cancelCommandDockPrompt();
      return;
    }
    if (industryCommandDock.deliverable || industryCommandDock.project) {
      clearCommandDockSelection();
    } else {
      setCommandDockExpanded(true);
    }
    input.focus({ preventScroll: true });
  });

  renderCommandDockItems();
  updateCommandDockContext();
  return industryCommandDock;
}

function setCommandDockExpanded(expanded) {
  const dock = ensureCommandDock();
  dock.expanded = !!expanded;
  dock.body.hidden = !dock.expanded;
  dock.root.dataset.expanded = String(dock.expanded);
  dock.expand.setAttribute("aria-expanded", String(dock.expanded));
  dock.expand.title = dock.expanded ? "Hide available actions" : "Show available actions";
  if (dock.expanded && !industryActivePrompt) filterCommandDock();
}

function getCommandDockProjectDeliverables(project, { includeAll = false, now = new Date() } = {}) {
  if (!project) return [];
  const list =
    typeof getOverviewDeliverables === "function"
      ? getOverviewDeliverables(project)
      : Array.isArray(project.deliverables)
        ? project.deliverables
        : [];
  const cutoff = new Date(now);
  cutoff.setHours(0, 0, 0, 0);
  cutoff.setDate(cutoff.getDate() - 30);
  const showAll = includeAll ||
    (typeof userSettings !== "undefined" && userSettings.commandLineShowAllDeliverables === true);
  const sorted = list.filter((candidate) => {
    if (!candidate) return false;
    if (showAll) return true;
    const due = parseDueStr(getEffectiveDueStr(candidate));
    return !due || due >= cutoff;
  });
  sorted.sort(compareDeliverablesByDueDesc);
  return sorted;
}

function updateCommandDockContext() {
  const dock = ensureCommandDock();
  const { deliverable, project } = dock;
  dock.context.classList.remove("has-selection", "has-project");
  if (deliverable) {
    const parts = [
      String(project?.id || "").trim(),
      String(deliverable?.name || "Deliverable").trim(),
      getProjectShortName(project),
    ].filter(Boolean);
    dock.context.textContent = parts.join(" · ");
    dock.context.classList.add("has-selection");
    dock.context.title = "Selected deliverable — click to go back to the project";
    dock.scope.textContent = "Acts on 1 deliverable";
    dock.input.placeholder = "Type a command · # to search projects…";
  } else if (project) {
    const parts = [String(project?.id || "").trim(), getProjectShortName(project)].filter(Boolean);
    dock.context.textContent = parts.join(" · ");
    dock.context.classList.add("has-project");
    dock.context.title = "Selected project — click to clear";
    dock.scope.textContent = "Project commands available · select a deliverable for more actions";
    dock.input.placeholder = dock.pendingKey
      ? "Now choose a deliverable · # to search…"
      : "Type a command · # to search projects or deliverables…";
  } else {
    dock.context.textContent = "No project selected";
    dock.context.title = "Type # then a project number or name, or click a row";
    dock.scope.textContent = "Select a project to run commands";
    dock.input.placeholder = dock.pendingKey
      ? "Now select a row or type # to search a project…"
      : "Type a command · # to search projects…";
  }
  if (dock.pendingKey) {
    const pending = dock.items.find(item => item.key === dock.pendingKey);
    const targetLabel = pending?.scope === "project" ? "project" : "deliverable";
    dock.pending.textContent = `${dock.pendingLabel} · waiting for a ${targetLabel}`;
    dock.pending.hidden = false;
  } else {
    dock.pending.hidden = true;
  }
  dock.root.classList.toggle("has-selection", !!deliverable);
  dock.root.classList.toggle("has-project", !!project && !deliverable);
  dock.root.classList.toggle("has-pending", !!dock.pendingKey);
}

// The "Target" group: projects until one is chosen, then that project's
// deliverables until one is chosen. Typing in the line searches it.
function buildCommandDockTargetGroup(deliverable, project) {
  if (deliverable) return null;
  if (project) {
    const items = getCommandDockProjectDeliverables(project).map((candidate) => {
      const state = getDeliverableRegisterState(candidate);
      const dateStr = String(candidate?.due || "").trim() || getHardDueStr(candidate);
      const meta = [state.status || (state.kind === "done" ? "" : "no status"), dateStr ? humanDate(dateStr) : "", state.kind === "late" ? state.stamp.text.toLowerCase() : state.sub]
        .filter(Boolean)
        .join(" · ");
      return {
        key: `deliverable:${candidate.id}`,
        kind: "deliverable",
        label: String(candidate?.name || "Deliverable"),
        search: `${candidate?.name || ""} ${meta}`,
        meta,
        railKind: state.kind,
        run: () => selectDeliverableForCommands(candidate, project, { expand: true }),
      };
    });
    return {
      key: "target",
      column: "left",
      label: `Deliverables · ${getProjectShortName(project)}`,
      items,
      limit: 12,
      empty: "No recent deliverables. Enable Show all deliverables in command line in Settings to see older entries.",
    };
  }
  const items = (Array.isArray(db) ? db : []).map((candidate) => {
    const id = String(candidate?.id || "").trim();
    const name = String(candidate?.name || "").trim();
    const client = getProjectClientLabel(candidate);
    const count = getCommandDockProjectDeliverables(candidate).length;
    return {
      key: `project:${id || name}`,
      kind: "project",
      label: name || id || "Project",
      prefix: id,
      search: `${id} ${name} ${client} ${candidate?.nick || ""}`,
      meta: [client, industryPlural(count, "deliverable")].filter(Boolean).join(" · "),
      run: () => selectProjectForCommands(candidate),
    };
  });
  return {
    key: "target",
    column: "left",
    label: "Projects",
    items,
    limit: 10,
    empty: "No projects yet.",
  };
}

// Every command, keyed so a pending action survives selection and re-renders.
function buildCommandDockGroups(deliverable, project) {
  const hasTarget = !!deliverable;
  const rerender = () => renderProjectsPreservingExpandedDeliverables();

  const statusItems = INDUSTRY_STATUS_OPTIONS.map((status) => ({
    key: `status:${status}`,
    label: status,
    kind: "status",
    checked: hasTarget && hasStatus(deliverable, status),
    run: async (target) => {
      setSingleStatus(target.deliverable, status);
      await save();
      rerender();
    },
  }));

  const deliverableItems = [
    {
      key: "add-to-timesheet",
      label: "Add to Timesheet",
      search: "add to timesheet log time hours day",
      run: (target) => startTimesheetHoursPrompt(target.project, target.deliverable),
    },
    {
      key: "add-deliverable",
      scope: "project",
      label: "Add Deliverable",
      search: "add deliverable new create deliverable description deadline",
      run: (target, query) => {
        let initialDesc = "";
        if (query) {
          const m = query.match(/^(?:add\s+deliverable|add\s+dlv|add)\s+(.+)$/i);
          if (m && m[1].trim()) initialDesc = m[1].trim();
        }
        startAddDeliverablePrompt(target.project, initialDesc);
      },
    },
    {
      key: "pin",
      label: hasTarget && isDeliverablePinned(deliverable) ? "Unpin deliverable" : "Pin deliverable",
      run: async (target) => {
        setDeliverablePinnedState(target.deliverable, !isDeliverablePinned(target.deliverable));
        await save();
        rerender();
      },
    },
    {
      key: "notes",
      scope: "project",
      label: "Open project notes",
      run: (target) => openProjectPage(target.project),
    },
    {
      key: "folder",
      scope: "project",
      label: "Open project folder",
      hidden: !!project && !project.path,
      run: async (target) => {
        if (!target.project?.path) {
          toast("This project has no folder path.");
          return;
        }
        if (!window.pywebview?.api?.open_path) {
          toast("Open path is unavailable.");
          return;
        }
        try {
          const result = await window.pywebview.api.open_path(convertPath(target.project.path));
          if (result?.status && result.status !== "success") {
            throw new Error(result.message || "Unable to open folder.");
          }
          toast("Opening folder...");
        } catch (error) {
          toast(error?.message || "Failed to open path.");
        }
      },
    },
    {
      key: "edit-project",
      scope: "project",
      label: "Edit project",
      run: (target) => {
        const index = Array.isArray(db) ? db.indexOf(target.project) : -1;
        if (index >= 0) openEdit(index);
      },
    },
    {
      key: "delete",
      label: "Delete deliverable",
      danger: true,
      run: (target) => removeDeliverable(target.project, target.deliverable),
    },
  ];

  const toolEntries = getDeliverableToolMenuEntries();
  const hotkeys = getCommandHotkeyEntries().map((entry) => ({
    ...entry,
    key: `hotkey:${entry.number}`,
    search: `${entry.number} ${entry.label}`,
    hintKey: `${entry.number} ↵`,
    shortcut: entry.number,
  }));
  const quickActions = DELIVERABLE_QUICK_ACCESS_ACTIONS.map((action, index) => ({
    key: `quick:${action.id}`,
    label: getDeliverableQuickAccessActionLabel(action),
    hintKey: index === 0 ? "Ctrl ⏎" : "",
    shortcut: index === 0 ? "Enter" : "",
    run: (target) => action.run(target.project, target.deliverable),
  }));
  const allTools = toolEntries
    .map((entry) => ({
      key: `tool:${entry.id}`,
      label: entry.menuLabel || entry.label,
      tag: true,
      scope: entry.id === "toolOpenCadFiles" ? "project" : undefined,
      run: (target) =>
        launchSharedToolCard(
          entry.id,
          buildProjectsTabToolLaunchContext(target.project, target.deliverable)
        ),
    }));

  const targetGroup = buildCommandDockTargetGroup(deliverable, project);
  const projectSearchGroup = project ? buildCommandDockTargetGroup(null, null) : null;
  if (projectSearchGroup) {
    projectSearchGroup.key = "project-search";
    projectSearchGroup.items = projectSearchGroup.items.map(item => ({ ...item, searchOnly: true }));
  }
  return [
    ...(targetGroup ? [targetGroup] : []),
    ...(projectSearchGroup ? [projectSearchGroup] : []),
    { key: "status", column: "left", label: "Status", items: statusItems },
    { key: "project", column: "left", label: "Project", items: deliverableItems.filter(item => item.scope === "project") },
    { key: "deliverable", column: "left", label: "Deliverable", items: deliverableItems.filter(item => item.scope !== "project") },
    { key: "hotkeys", column: "right", label: "Hotkeys", items: hotkeys, empty: "Assign numbers in Settings → Hotkeys." },
    { key: "quick-access", column: "right", label: "Quick access", items: quickActions },
    { key: "tools-all", column: "right", label: "Tools · all", items: allTools, tags: true },
  ];
}

function findDeliverableElement(deliverable) {
  const id = String(deliverable?.id || "").trim();
  if (!id) return null;
  const selector = `[data-deliverable-id="${CSS.escape(id)}"]`;
  return (
    document.querySelector(`#projectsCardView ${selector}`) ||
    document.querySelector(`#tbody ${selector}`)
  );
}

function renderCommandDockItems() {
  const dock = industryCommandDock;
  const groups = buildCommandDockGroups(dock.deliverable, dock.project);
  dock.left.innerHTML = "";
  dock.right.innerHTML = "";
  dock.items = [];
  dock.sections = [];
  dock.activeIndex = -1;

  groups.forEach((group) => {
    const host = group.column === "left" ? dock.left : dock.right;
    const section = el("div", { className: `cmd-group cmd-group--${group.key}` });
    section.appendChild(el("div", { className: "reg-kick cmd-group-label", textContent: group.label }));
    const list = el("div", { className: `cmd-list${group.tags ? " cmd-list--tags" : ""}` });
    group.items.forEach((item) => {
      if (item.hidden) return;
      const isTarget = item.kind === "project" || item.kind === "deliverable";
      const node = el("button", {
        type: "button",
        className: `cmd-item${item.tag ? " cmd-item--tag" : ""}${item.danger ? " is-danger" : ""}${
          item.kind === "status" ? " cmd-item--status" : ""
        }${isTarget ? ` cmd-item--target cmd-item--${item.kind}` : ""}${item.checked ? " is-checked" : ""}`,
      });
      node.setAttribute("role", "menuitem");
      node.dataset.commandKey = item.key;
      if (item.kind === "status") {
        node.appendChild(el("span", { className: "cmd-radio", "aria-hidden": "true" }));
      }
      if (item.kind === "deliverable") {
        node.appendChild(el("span", { className: `reg-rail reg-rail--${getRailForKind(item.railKind)} cmd-item-rail` }));
      }
      if (item.prefix) {
        node.appendChild(el("span", { className: "reg-kick cmd-item-prefix", textContent: item.prefix }));
      }
      node.appendChild(el("span", { className: "cmd-item-label", textContent: item.label }));
      if (item.meta) {
        node.appendChild(el("span", { className: "cmd-item-meta", textContent: item.meta }));
      }
      if (item.hintKey) {
        node.appendChild(el("span", { className: "reg-kick cmd-key-hint", textContent: item.hintKey }));
      }
      node.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        runCommandDockItem(item);
      });
      node.addEventListener("mousemove", () => {
        const index = dock.items.findIndex((entry) => entry.node === node);
        if (index >= 0 && index !== dock.activeIndex) setCommandDockActive(index);
      });
      list.appendChild(node);
      dock.items.push({ ...item, node, group: group.key, section });
    });
    section.appendChild(list);
    const more = el("div", { className: "cmd-more reg-kick" });
    more.hidden = true;
    section.appendChild(more);
    if (!group.items.length && group.empty) {
      section.appendChild(el("div", { className: "cmd-empty", textContent: group.empty }));
    }
    dock.sections.push({ key: group.key, section, limit: group.limit || 0, more });
    host.appendChild(section);
  });
  filterCommandDock();
}

function getRailForKind(kind) {
  if (kind === "late") return "hatch";
  if (kind === "nostatus") return "dashed";
  if (kind === "done") return "muted";
  return "accent";
}

// Commands default to requiring a deliverable; project commands opt in to
// running with just a project. Both support choosing the command first.
function runCommandDockItem(item) {
  const dock = industryCommandDock;
  if (!item) return;
  if (item.kind === "project" || item.kind === "deliverable") {
    dock.input.value = "";
    item.run?.();
    return;
  }
  const needsProject = item.scope === "project";
  if (needsProject ? !dock.project : !dock.deliverable) {
    dock.pendingKey = item.key;
    dock.pendingLabel = item.label;
    dock.input.value = "";
    filterCommandDock();
    updateCommandDockContext();
    toast(`${item.label} — now select a ${needsProject ? "project" : "deliverable"}.`);
    return;
  }
  const target = { deliverable: dock.deliverable, project: dock.project };
  // A "#" query is a target search, never argument text for the command.
  const parsed = parseCommandDockQuery(dock.input.value);
  const query = parsed.targetMode ? "" : dock.input.value.trim();
  dock.pendingKey = null;
  dock.pendingLabel = "";
  dock.input.value = "";
  filterCommandDock();
  updateCommandDockContext();
  try {
    const result = item.run?.(target, query);
    if (result && typeof result.catch === "function") {
      result.catch((error) => {
        console.warn("Command failed:", error);
        toast(error?.message || "Command failed.");
      });
    }
  } finally {
    if (!industryActivePrompt) {
      setCommandDockExpanded(false);
      dock.input.blur();
    }
  }
}

function getVisibleCommandDockItems() {
  return industryCommandDock.items.filter((item) => !item.node.hidden);
}

function setCommandDockActive(index) {
  const dock = industryCommandDock;
  dock.items.forEach((item) => item.node.classList.remove("is-active"));
  dock.activeIndex = -1;
  const item = dock.items[index];
  if (!item || item.node.hidden) return;
  item.node.classList.add("is-active");
  dock.activeIndex = index;
  if (dock.expanded) item.node.scrollIntoView?.({ block: "nearest" });
}

function moveCommandDockActive(step) {
  const dock = industryCommandDock;
  const visible = getVisibleCommandDockItems();
  if (!visible.length) return;
  const currentVisibleIndex = visible.findIndex((item) => item === dock.items[dock.activeIndex]);
  let nextVisible = currentVisibleIndex + step;
  if (nextVisible < 0) nextVisible = visible.length - 1;
  if (nextVisible >= visible.length) nextVisible = 0;
  setCommandDockActive(dock.items.indexOf(visible[nextVisible]));
}

function moveCommandDockSpatial(direction) {
  const dock = industryCommandDock;
  const visible = getVisibleCommandDockItems();
  if (!visible.length) return;

  const currentIndex = visible.findIndex((item) => item === dock.items[dock.activeIndex]);
  if (currentIndex < 0) {
    const target = (direction === "left" || direction === "up") ? visible.length - 1 : 0;
    setCommandDockActive(dock.items.indexOf(visible[target]));
    return;
  }

  const current = visible[currentIndex];
  const cRect = current?.node?.getBoundingClientRect?.() || { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0 };
  const hasDimensions = cRect.width > 0 && cRect.height > 0;

  if (!hasDimensions) {
    const step = (direction === "right" || direction === "down") ? 1 : -1;
    moveCommandDockActive(step);
    return;
  }

  const cCenter = {
    x: cRect.left + cRect.width / 2,
    y: cRect.top + cRect.height / 2,
  };

  let best = null;
  let bestScore = Infinity;

  visible.forEach((candidate) => {
    if (candidate === current) return;
    const r = candidate.node?.getBoundingClientRect?.();
    if (!r || r.width <= 0 || r.height <= 0) return;
    const center = { x: r.left + r.width / 2, y: r.top + r.height / 2 };

    if (direction === "right") {
      if (center.x <= cCenter.x + 4 && r.left < cRect.left + 8) return;
      const dx = Math.max(0, r.left - cRect.right);
      const dy = Math.abs(center.y - cCenter.y);
      const isSameRow = r.bottom > cRect.top + 4 && r.top < cRect.bottom - 4;
      const score = isSameRow ? (dx + dy * 0.2) : (dx + dy * 2.5 + (center.y > cCenter.y ? 0 : 40));
      if (score < bestScore) {
        bestScore = score;
        best = candidate;
      }
    } else if (direction === "left") {
      if (center.x >= cCenter.x - 4 && r.right > cRect.right - 8) return;
      const dx = Math.max(0, cRect.left - r.right);
      const dy = Math.abs(center.y - cCenter.y);
      const isSameRow = r.bottom > cRect.top + 4 && r.top < cRect.bottom - 4;
      const score = isSameRow ? (dx + dy * 0.2) : (dx + dy * 2.5 + (center.y < cCenter.y ? 0 : 40));
      if (score < bestScore) {
        bestScore = score;
        best = candidate;
      }
    } else if (direction === "down") {
      if (center.y <= cCenter.y + 4 && r.top < cRect.top + 8) return;
      const dy = Math.max(0, r.top - cRect.bottom);
      const dx = Math.abs(center.x - cCenter.x);
      const isSameCol = r.right > cRect.left + 4 && r.left < cRect.right - 4;
      const score = isSameCol ? (dy + dx * 0.2) : (dy + dx * 2);
      if (score < bestScore) {
        bestScore = score;
        best = candidate;
      }
    } else if (direction === "up") {
      if (center.y >= cCenter.y - 4 && r.bottom > cRect.bottom - 8) return;
      const dy = Math.max(0, cRect.top - r.bottom);
      const dx = Math.abs(center.x - cCenter.x);
      const isSameCol = r.right > cRect.left + 4 && r.left < cRect.right - 4;
      const score = isSameCol ? (dy + dx * 0.2) : (dy + dx * 2);
      if (score < bestScore) {
        bestScore = score;
        best = candidate;
      }
    }
  });

  if (best) {
    setCommandDockActive(dock.items.indexOf(best));
  } else {
    if (direction === "right") {
      let wrapTarget = null;
      let minX = Infinity;
      visible.forEach((candidate) => {
        const r = candidate.node?.getBoundingClientRect?.();
        if (r && r.left < minX) {
          minX = r.left;
          wrapTarget = candidate;
        }
      });
      setCommandDockActive(dock.items.indexOf(wrapTarget || visible[(currentIndex + 1) % visible.length]));
    } else if (direction === "left") {
      let wrapTarget = null;
      let maxX = -Infinity;
      visible.forEach((candidate) => {
        const r = candidate.node?.getBoundingClientRect?.();
        if (r && r.right > maxX) {
          maxX = r.right;
          wrapTarget = candidate;
        }
      });
      setCommandDockActive(dock.items.indexOf(wrapTarget || visible[(currentIndex - 1 + visible.length) % visible.length]));
    } else if (direction === "down") {
      moveCommandDockActive(1);
    } else if (direction === "up") {
      moveCommandDockActive(-1);
    }
  }
}

// The line searches commands by default; a leading "#" switches it to
// searching targets (projects, then the chosen project's deliverables).
function parseCommandDockQuery(rawValue) {
  const trimmed = String(rawValue || "").trim();
  const targetMode = trimmed.startsWith("#");
  const query = (targetMode ? trimmed.slice(1) : trimmed).trim().toLowerCase();
  return { targetMode, query, tokens: query.split(/\s+/).filter(Boolean) };
}

function isCommandDockTargetItem(item) {
  return item.kind === "project" || item.kind === "deliverable";
}

function commandDockWithinOneEdit(left, right) {
  if (Math.abs(left.length - right.length) > 1) return false;
  let index = 0;
  while (index < Math.min(left.length, right.length) && left[index] === right[index]) index++;
  if (index === Math.min(left.length, right.length)) return true;
  if (left.length < right.length) return left.slice(index) === right.slice(index + 1);
  if (left.length > right.length) return left.slice(index + 1) === right.slice(index);
  return left.slice(index + 1) === right.slice(index + 1) || (
    left[index] === right[index + 1] && left[index + 1] === right[index] &&
    left.slice(index + 2) === right.slice(index + 2)
  );
}

function scoreCommandDockMatch(item, query, tokens) {
  const label = String(item.label || "").toLowerCase();
  const haystack = `${item.search || ""} ${label}`.toLowerCase();
  if (label === query) return 0;
  if (haystack.includes(query)) return 1;
  const words = haystack.match(/[\p{L}\p{N}]+/gu) || [];
  let typos = 0;
  for (const token of tokens) {
    if (haystack.includes(token)) continue;
    // Short fragments and identifiers stay literal to avoid noisy matches.
    if (token.length < 3 || !/^\p{L}+$/u.test(token) || !words.some(word =>
      word.length >= 3 && /^\p{L}+$/u.test(word) && commandDockWithinOneEdit(token, word)
    )) return Infinity;
    typos++;
  }
  return typos ? 10 + typos : 2;
}

function filterCommandDock() {
  const dock = industryCommandDock;
  const { targetMode, query, tokens } = parseCommandDockQuery(dock.input.value);
  const hasQuery = targetMode || tokens.length > 0;
  const matches = (item) => {
    if (isCommandDockTargetItem(item)) {
      // Targets browse freely while the line is empty, but only "#" searches them.
      if (!targetMode) return !tokens.length && !item.searchOnly;
      if (!tokens.length) return true;
      return true;
    }
    if (targetMode) return false;
    if (tokens.length === 1 && /^\d+$/.test(tokens[0])) return item.key === `hotkey:${tokens[0]}`;
    if (!tokens.length) return !item.searchOnly;
    return true;
  };
  const current = dock.items[dock.activeIndex];
  dock.items.forEach((item, index) => {
    item.searchOrder ??= index;
    const numericShortcut = !targetMode && /^\d+$/.test(query);
    item.matchScore = matches(item) ? (tokens.length && !numericShortcut ? scoreCommandDockMatch(item, query, tokens) : 0) : Infinity;
    item.node.hidden = !Number.isFinite(item.matchScore);
  });
  // Keep the grouped layout, ranking matches within each group before its limit.
  const sections = dock.sections || [];
  dock.items.sort((a, b) =>
    sections.findIndex(entry => entry.section === a.section) - sections.findIndex(entry => entry.section === b.section) ||
    (tokens.length ? a.matchScore - b.matchScore : 0) || a.searchOrder - b.searchOrder
  );
  dock.items.forEach(item => item.node.parentNode?.appendChild(item.node));
  // Long target lists show only the first few until the query narrows them.
  (dock.sections || []).forEach(({ section, limit, more }) => {
    if (!limit) return;
    const sectionItems = dock.items.filter((item) => item.section === section && !item.node.hidden);
    sectionItems.forEach((item, index) => {
      if (index >= limit) item.node.hidden = true;
    });
    const overflow = sectionItems.length - limit;
    more.hidden = overflow <= 0;
    if (overflow > 0) {
      more.textContent = `+${overflow} more · keep typing to narrow`;
    }
  });
  (dock.sections || []).forEach(({ section }) => {
    const anyVisible = dock.items.some((item) => item.section === section && !item.node.hidden);
    const hasEmptyNote = !!section.querySelector(".cmd-empty");
    section.hidden = !anyVisible && !(hasEmptyNote && !hasQuery);
  });
  const visible = getVisibleCommandDockItems();
  if (hasQuery) {
    const best = visible.reduce((result, item) => !result || item.matchScore < result.matchScore ? item : result, null);
    const selected = current && !current.node.hidden && current.matchScore === best?.matchScore ? current : best;
    setCommandDockActive(selected ? dock.items.indexOf(selected) : -1);
  } else if (current && current.node.hidden) {
    setCommandDockActive(-1);
  } else if (current) {
    setCommandDockActive(dock.items.indexOf(current));
  }
}

function focusCommandDockGroup(focus) {
  const dock = industryCommandDock;
  let index = -1;
  if (focus === "status") {
    index = dock.items.findIndex((item) => item.kind === "status" && item.checked);
    if (index < 0) index = dock.items.findIndex((item) => item.kind === "status");
  } else if (focus === "tools") {
    index = dock.items.findIndex((item) => item.group === "hotkeys" || item.group === "tools-all");
  }
  if (index >= 0) setCommandDockActive(index);
}

function handleCommandDockKeydown(event) {
  const dock = industryCommandDock;
  if (!dock) return;
  if (industryActivePrompt) {
    handleCommandDockPromptKeydown(event);
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    if (!dock.expanded) setCommandDockExpanded(true);
    moveCommandDockSpatial("down");
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    if (!dock.expanded) setCommandDockExpanded(true);
    moveCommandDockSpatial("up");
    return;
  }
  if (event.key === "ArrowRight") {
    const isInput = event.target === dock.input;
    const atEnd = isInput && dock.input.selectionStart === dock.input.value.length && dock.input.selectionEnd === dock.input.value.length;
    if (!isInput || dock.input.value === "" || atEnd) {
      event.preventDefault();
      if (!dock.expanded) setCommandDockExpanded(true);
      moveCommandDockSpatial("right");
      return;
    }
  }
  if (event.key === "ArrowLeft") {
    const isInput = event.target === dock.input;
    const atStart = isInput && dock.input.selectionStart === 0 && dock.input.selectionEnd === 0;
    if (!isInput || dock.input.value === "" || atStart) {
      event.preventDefault();
      if (!dock.expanded) setCommandDockExpanded(true);
      moveCommandDockSpatial("left");
      return;
    }
  }
  if (event.key === "Enter") {
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      const quick = dock.items.find((item) => item.shortcut === "Enter");
      if (quick) runCommandDockItem(quick);
      return;
    }
    const active = dock.items[dock.activeIndex];
    if (active && !active.node.hidden) {
      runCommandDockItem(active);
      return;
    }
    const visible = getVisibleCommandDockItems();
    if (dock.input.value.trim() && visible.length === 1) runCommandDockItem(visible[0]);
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    if (dock.input.value) {
      dock.input.value = "";
      filterCommandDock();
    } else if (dock.pendingKey) {
      dock.pendingKey = null;
      dock.pendingLabel = "";
      updateCommandDockContext();
    } else if (dock.deliverable || dock.project) {
      clearCommandDockSelection();
    } else if (dock.expanded) {
      setCommandDockExpanded(false);
    } else {
      dock.input.blur();
    }
    return;
  }
  if ((event.ctrlKey || event.metaKey) && /^[1-9]$/.test(event.key)) {
    const target = dock.items.find((item) => item.shortcut === event.key);
    if (target) {
      event.preventDefault();
      runCommandDockItem(target);
    }
  }
}

// ---------------------------------------------------------------------------
// 1d — Command line interactive prompts (e.g. Add Deliverable)
// ---------------------------------------------------------------------------

let industryActivePrompt = null;

function parsePromptDate(text) {
  if (!text) return null;
  const s = String(text).trim().toLowerCase();
  if (!s) return null;

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  if (s === "today") return today;
  if (s === "tomorrow") {
    const d = new Date(today);
    d.setDate(today.getDate() + 1);
    return d;
  }
  if (s === "friday" || s === "this friday") {
    const d = new Date(today);
    const day = today.getDay();
    const diff = (5 - day + 7) % 7 || 7;
    d.setDate(today.getDate() + diff);
    return d;
  }
  if (s === "next friday") {
    const d = new Date(today);
    const day = today.getDay();
    const diff = ((5 - day + 7) % 7 || 7) + 7;
    d.setDate(today.getDate() + diff);
    return d;
  }
  if (s === "next week" || s === "in 1 week") {
    const d = new Date(today);
    d.setDate(today.getDate() + 7);
    return d;
  }
  if (s === "2 weeks" || s === "in 2 weeks") {
    const d = new Date(today);
    d.setDate(today.getDate() + 14);
    return d;
  }
  if (s === "end of month" || s === "eom" || s === "in 1 month" || s === "1 month") {
    return new Date(today.getFullYear(), today.getMonth() + 1, 0);
  }

  // Check month/day format without year: "9/15" or "09/15"
  const m = s.match(/^(\d{1,2})[\/\.-](\d{1,2})$/);
  if (m) {
    const mm = parseInt(m[1], 10);
    const dd = parseInt(m[2], 10);
    const year = today.getFullYear();
    const candidate = new Date(year, mm - 1, dd, 12, 0, 0);
    if (!isNaN(candidate.getTime())) {
      return candidate;
    }
  }

  if (typeof parseDueStr === "function") {
    const parsed = parseDueStr(text);
    if (parsed && !isNaN(parsed.getTime())) return parsed;
  }

  const candidate = new Date(text);
  return isNaN(candidate.getTime()) ? null : candidate;
}

function formatPromptDate(date) {
  if (!(date instanceof Date) || isNaN(date.getTime())) return "";
  if (typeof formatDueDateShort === "function") {
    return formatDueDateShort(date);
  }
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const yyyy = date.getFullYear();
  return `${mm}/${dd}/${yyyy}`;
}

function parseTimesheetPromptDate(text) {
  const raw = String(text || "today").trim().toLowerCase();
  if (raw === "today" || raw === "yesterday") {
    const date = new Date();
    date.setHours(12, 0, 0, 0);
    if (raw === "yesterday") date.setDate(date.getDate() - 1);
    return date;
  }
  const iso = raw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  const us = raw.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{4}))?$/);
  if (!iso && !us) return null;
  const year = Number(iso ? iso[1] : us[3] || new Date().getFullYear());
  const month = Number(iso ? iso[2] : us[1]);
  const day = Number(iso ? iso[3] : us[2]);
  const date = new Date(year, month - 1, day, 12);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day ? date : null;
}

function startTimesheetHoursPrompt(project, deliverable) {
  if (!project || !deliverable) return;
  const dock = ensureCommandDock();
  industryActivePrompt = {
    type: "timesheet-hours", project, deliverable, step: 0,
    values: { hours: "", date: "" },
  };
  dock.columns.hidden = true;
  dock.promptView.hidden = false;
  setCommandDockExpanded(true);
  renderPromptView();
  syncPromptInput();
}

async function advanceTimesheetHoursPrompt(raw) {
  const prompt = industryActivePrompt;
  if (!prompt || prompt.saving) return;
  if (prompt.step === 0) {
    const hours = Number(raw);
    if (!raw || !Number.isFinite(hours) || hours <= 0 || hours > 24 ||
        Math.abs(hours * 10 - Math.round(hours * 10)) > 1e-8) {
      toast("Enter hours greater than 0, up to 24, in increments of 0.1.");
      return;
    }
    prompt.values.hours = String(hours);
    setPromptStep(1);
    return;
  }
  const date = parseTimesheetPromptDate(raw);
  if (!date) {
    toast("Enter a valid date: MM/DD/YYYY, YYYY-MM-DD, today, or yesterday.");
    return;
  }
  prompt.values.date = raw;
  prompt.saving = true;
  try {
    const result = await addDeliverableHoursToTimesheet(prompt.project, prompt.deliverable, prompt.values.hours, date);
    if (industryActivePrompt === prompt) {
      cancelCommandDockPrompt({ silent: true });
      setCommandDockExpanded(false);
      industryCommandDock?.input?.blur();
    }
    toast(`Added ${result.hours} hours to ${getProjectShortName(prompt.project)} for ${formatPromptDate(date)}.`);
  } catch (error) {
    toast(error?.message || "Failed to add timesheet hours.");
  } finally {
    prompt.saving = false;
  }
}

function renderTimesheetHoursPrompt() {
  const dock = industryCommandDock;
  const { project, deliverable, step, values } = industryActivePrompt;
  const host = dock.promptView;
  host.innerHTML = "";
  const cancel = el("button", { type: "button", className: "cmd-prompt-cancel-btn", textContent: "✕ Cancel" });
  cancel.addEventListener("click", () => cancelCommandDockPrompt());
  const header = el("div", { className: "cmd-prompt-header" });
  header.append(el("div", { className: "cmd-prompt-title", textContent: `Add to Timesheet · ${getProjectShortName(project)} · ${deliverable.name || "Deliverable"}` }), cancel);
  const guide = el("div", { className: "cmd-prompt-guide" });
  guide.append(el("div", { className: "cmd-prompt-instruction", textContent: step === 0 ? "Step 1 of 2: Enter hours to add." : `Step 2 of 2: Add ${values.hours} hours on which date?` }));
  guide.append(el("div", { className: "cmd-prompt-subinstruction", textContent: step === 0 ? "Use increments of 0.1 hours. Existing project hours will be increased." : "Press Enter for today, or enter MM/DD/YYYY, YYYY-MM-DD, or yesterday. The date selects the timesheet week." }));
  const chips = el("div", { className: "cmd-prompt-chips" });
  (step === 0 ? ["0.5", "1", "2", "4", "8"] : ["Today", "Yesterday"]).forEach((value) => {
    const button = el("button", { type: "button", className: "cmd-prompt-chip", textContent: value });
    button.addEventListener("click", () => advancePromptStep(value));
    chips.append(button);
  });
  guide.append(chips);
  host.append(header, guide);
}

function startAddDeliverablePrompt(project, initialDescription = "") {
  if (!project) {
    toast("Please select a project first.");
    return;
  }
  const dock = ensureCommandDock();
  const initialName = String(initialDescription || "").trim();
  industryActivePrompt = {
    type: "add-deliverable",
    project,
    step: initialName ? 1 : 0,
    values: {
      name: initialName,
      due: "",
      hardDue: "",
    },
  };

  dock.columns.hidden = true;
  dock.promptView.hidden = false;
  setCommandDockExpanded(true);
  renderPromptView();
  syncPromptInput();
}

function syncPromptInput() {
  const dock = industryCommandDock;
  if (!dock || !industryActivePrompt) return;
  const { step, values } = industryActivePrompt;

  dock.root.classList.add("has-pending");
  if (industryActivePrompt.type === "timesheet-hours") {
    dock.pending.textContent = `Add to Timesheet · ${step + 1}/2 ${step === 0 ? "Hours" : "Date"}`;
    dock.pending.hidden = false;
    dock.input.placeholder = step === 0 ? "Hours to add (e.g. 2.5)…" : "Date (MM/DD/YYYY), or press Enter for today…";
    dock.input.value = step === 0 ? values.hours : values.date;
    dock.scope.textContent = step === 0 ? "↩ continue · esc cancel" : "↩ add hours · ⌫ back · esc cancel";
    if (dock.footShortcuts) dock.footShortcuts.textContent = dock.scope.textContent;
    dock.input.focus({ preventScroll: true });
    if (dock.input.value) dock.input.select();
    return;
  }
  if (step === 0) {
    dock.pending.textContent = "Add Deliverable · 1/3 Description";
    dock.pending.hidden = false;
    dock.input.placeholder = "Enter deliverable description (e.g. DD90) and press Enter…";
    dock.input.value = values.name || "";
    dock.scope.textContent = "Step 1 of 3: Description · ↩ continue · esc cancel";
    if (dock.footShortcuts) dock.footShortcuts.textContent = "↩ continue · esc cancel";
  } else if (step === 1) {
    dock.pending.textContent = "Add Deliverable · 2/3 Internal Deadline";
    dock.pending.hidden = false;
    dock.input.placeholder = "Enter internal deadline (MM/DD/YYYY) or press Enter to skip…";
    dock.input.value = values.due || "";
    dock.scope.textContent = "Step 2 of 3: Internal Deadline · ↩ continue · ⌫ back · esc cancel";
    if (dock.footShortcuts) dock.footShortcuts.textContent = "↩ continue · ⌫ back · esc cancel";
  } else if (step === 2) {
    dock.pending.textContent = "Add Deliverable · 3/3 External Deadline";
    dock.pending.hidden = false;
    dock.input.placeholder = "Enter external deadline (MM/DD/YYYY) or press Enter to complete…";
    dock.input.value = values.hardDue || "";
    dock.scope.textContent = "Step 3 of 3: External Deadline · ↩ complete · ⌫ back · esc cancel";
    if (dock.footShortcuts) dock.footShortcuts.textContent = "↩ complete · ⌫ back · esc cancel";
  }
  dock.input.focus({ preventScroll: true });
  if (dock.input.value) {
    dock.input.select();
  }
}

function setPromptStep(stepIndex) {
  if (!industryActivePrompt) return;
  if (industryActivePrompt.saving) return;
  const lastStep = industryActivePrompt.type === "timesheet-hours" ? 1 : 2;
  industryActivePrompt.step = Math.max(0, Math.min(lastStep, stepIndex));
  renderPromptView();
  syncPromptInput();
}

function advancePromptStep(forcedValue) {
  const dock = industryCommandDock;
  if (!dock || !industryActivePrompt) return;
  const raw = String(forcedValue !== undefined ? forcedValue : dock.input.value).trim();
  if (industryActivePrompt.type === "timesheet-hours") {
    return advanceTimesheetHoursPrompt(raw);
  }
  const { step, values } = industryActivePrompt;

  if (step === 0) {
    if (!raw) {
      toast("Please enter a deliverable description.");
      dock.input.focus({ preventScroll: true });
      return;
    }
    values.name = raw;
    setPromptStep(1);
  } else if (step === 1) {
    if (!raw || raw.toLowerCase() === "skip" || raw.toLowerCase() === "none") {
      values.due = "";
      setPromptStep(2);
      return;
    }
    const d = parsePromptDate(raw);
    if (!d) {
      toast("Invalid date format. Use MM/DD/YYYY (or press Enter to skip).");
      return;
    }
    values.due = formatPromptDate(d);
    setPromptStep(2);
  } else if (step === 2) {
    if (!raw || raw.toLowerCase() === "skip" || raw.toLowerCase() === "none") {
      values.hardDue = "";
      completeAddDeliverablePrompt();
      return;
    }
    if (raw.toLowerCase() === "same" || raw.toLowerCase() === "same as internal") {
      values.hardDue = values.due || "";
      completeAddDeliverablePrompt();
      return;
    }
    const d = parsePromptDate(raw);
    if (!d) {
      toast("Invalid date format. Use MM/DD/YYYY (or press Enter to complete).");
      return;
    }
    values.hardDue = formatPromptDate(d);
    completeAddDeliverablePrompt();
  }
}

async function completeAddDeliverablePrompt() {
  if (!industryActivePrompt) return;
  const { project, values } = industryActivePrompt;
  const name = String(values.name || "").trim() || "Deliverable";
  const due = String(values.due || "").trim();
  const hardDue = String(values.hardDue || "").trim();

  const deliverable = typeof createDeliverable === "function"
    ? createDeliverable({ name, due, hardDue })
    : {
        id: "dlv-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
        name,
        due,
        hardDue,
        statuses: [],
        statusTags: [],
        attachments: [],
        noteItems: [],
        tasks: [],
      };

  if (!Array.isArray(project.deliverables)) {
    project.deliverables = [];
  }
  project.deliverables.push(deliverable);

  cancelCommandDockPrompt({ silent: true });

  if (typeof save === "function") {
    try {
      await save();
    } catch (err) {
      console.warn("Failed to save after adding deliverable:", err);
    }
  }

  if (typeof renderProjectsPreservingExpandedDeliverables === "function") {
    renderProjectsPreservingExpandedDeliverables();
  } else if (typeof render === "function") {
    render();
  }

  selectDeliverableForCommands(deliverable, project, { expand: false });
  setCommandDockExpanded(false);
  industryCommandDock?.input?.blur();
  toast(`Added deliverable "${name}" to ${getProjectShortName(project)}.`);
}

function cancelCommandDockPrompt({ silent = false } = {}) {
  const promptLabel = industryActivePrompt?.type === "timesheet-hours" ? "Add to Timesheet" : "Add Deliverable";
  if (industryActivePrompt?.saving && !silent) return;
  industryActivePrompt = null;
  const dock = industryCommandDock;
  if (!dock) return;

  if (dock.promptView) {
    dock.promptView.hidden = true;
    dock.promptView.innerHTML = "";
  }
  if (dock.columns) {
    dock.columns.hidden = false;
  }

  dock.pendingKey = null;
  dock.pendingLabel = "";
  dock.input.value = "";
  if (dock.footShortcuts) {
    dock.footShortcuts.textContent = "←→ ↑↓ move · ↩ run · esc clear / collapse";
  }
  renderCommandDockItems();
  updateCommandDockContext();
  if (!silent) {
    toast(`Cancelled ${promptLabel}.`);
  }
  dock.input.focus({ preventScroll: true });
}

function handleCommandDockPromptKeydown(event) {
  const dock = industryCommandDock;
  if (!dock || !industryActivePrompt) return;

  if (event.key === "Escape") {
    event.preventDefault();
    cancelCommandDockPrompt();
    return;
  }
  if (event.key === "Backspace" && dock.input.value === "") {
    event.preventDefault();
    if (industryActivePrompt.step > 0) {
      setPromptStep(industryActivePrompt.step - 1);
    }
    return;
  }
  if (event.key === "ArrowLeft") {
    const isInput = event.target === dock.input;
    const atStart = !isInput || (dock.input.selectionStart === 0 && dock.input.selectionEnd === 0);
    if ((!isInput || dock.input.value === "" || atStart) && industryActivePrompt.step > 0) {
      event.preventDefault();
      setPromptStep(industryActivePrompt.step - 1);
      return;
    }
  }
  if (event.key === "ArrowRight") {
    const isInput = event.target === dock.input;
    const atEnd = !isInput || (dock.input.selectionStart === dock.input.value.length && dock.input.selectionEnd === dock.input.value.length);
    if (!isInput || dock.input.value === "" || atEnd) {
      if (industryActivePrompt.step > 0 || dock.input.value.trim()) {
        event.preventDefault();
        advancePromptStep();
        return;
      }
    }
  }
  if (event.key === "Enter") {
    event.preventDefault();
    advancePromptStep();
    return;
  }
  if (event.key === "Tab") {
    event.preventDefault();
    if (event.shiftKey) {
      if (industryActivePrompt.step > 0) {
        setPromptStep(industryActivePrompt.step - 1);
      }
    } else {
      advancePromptStep();
    }
    return;
  }
}

function handleCommandDockPromptInput() {
  if (!industryActivePrompt) return;
  const dock = industryCommandDock;
  if (!dock) return;
  const liveVal = dock.input.value.trim();
  const { step, values } = industryActivePrompt;

  const previewName = dock.promptView.querySelector('[data-preview="name"]');
  const previewDue = dock.promptView.querySelector('[data-preview="due"]');
  const previewHardDue = dock.promptView.querySelector('[data-preview="hardDue"]');

  if (step === 0 && previewName) {
    previewName.textContent = liveVal || "Untitled";
  } else if (step === 1 && previewDue) {
    previewDue.textContent = liveVal || "—";
  } else if (step === 2 && previewHardDue) {
    previewHardDue.textContent = liveVal || "—";
  }
}

function renderPromptView() {
  const dock = industryCommandDock;
  if (!dock || !industryActivePrompt) return;
  if (industryActivePrompt.type === "timesheet-hours") return renderTimesheetHoursPrompt();
  const { project, step, values } = industryActivePrompt;
  const host = dock.promptView;
  host.innerHTML = "";

  // 1. Header
  const header = el("div", { className: "cmd-prompt-header" });
  const title = el("div", { className: "cmd-prompt-title" });
  title.append(
    el("span", { className: "reg-kick cmd-prompt-tag", textContent: "Add Deliverable" }),
    el("span", {
      className: "cmd-prompt-project-name",
      textContent: `${project?.id ? project.id + " · " : ""}${getProjectShortName(project)}`,
    })
  );
  const cancelBtn = el("button", {
    type: "button",
    className: "cmd-prompt-cancel-btn",
    textContent: "✕ Cancel",
    title: "Cancel (Esc)",
  });
  cancelBtn.addEventListener("click", () => cancelCommandDockPrompt());
  header.append(title, cancelBtn);

  // 2. Stepper
  const stepper = el("div", { className: "cmd-prompt-stepper" });
  const stepsConfig = [
    { label: "Description", val: values.name },
    { label: "Internal Deadline", val: values.due || "None" },
    { label: "External Deadline", val: values.hardDue || "None" },
  ];
  stepsConfig.forEach((cfg, idx) => {
    if (idx > 0) {
      stepper.appendChild(el("span", { className: "cmd-prompt-step-divider", textContent: "›" }));
    }
    const stepEl = el("div", {
      className: `cmd-prompt-step${idx === step ? " is-active" : ""}${idx < step ? " is-completed" : ""}`,
      title: idx < step ? `Click to edit ${cfg.label}` : "",
    });
    const numEl = el("span", {
      className: "cmd-prompt-step-num",
      textContent: idx < step ? "✓" : String(idx + 1),
    });
    const infoEl = el("div", { className: "cmd-prompt-step-info" });
    infoEl.append(
      el("span", { className: "cmd-prompt-step-label", textContent: cfg.label }),
      el("span", {
        className: "cmd-prompt-step-val",
        textContent: idx < step ? cfg.val : idx === step ? "Active" : "Upcoming",
      })
    );
    stepEl.append(numEl, infoEl);
    if (idx < step) {
      stepEl.addEventListener("click", () => setPromptStep(idx));
    }
    stepper.appendChild(stepEl);
  });

  // 3. Body: Guide (left) & Preview (right)
  const body = el("div", { className: "cmd-prompt-body" });
  const guide = el("div", { className: "cmd-prompt-guide" });

  let instructionText = "";
  let subinstructionText = "";
  let chipsList = [];

  if (step === 0) {
    instructionText = "Enter a name or description for this deliverable.";
    subinstructionText = "e.g. DD90, 50% CD, Permit Set, Plan Check Responses, or select a preset below:";
    chipsList = [
      { label: "DD90", value: "DD90" },
      { label: "50% CD", value: "50% CD" },
      { label: "100% CD", value: "100% CD" },
      { label: "IFP", value: "IFP" },
      { label: "Plan Check Response", value: "Plan Check Response" },
      { label: "As-Built", value: "As-Built" },
    ];
  } else if (step === 1) {
    instructionText = "Enter the internal target deadline for the engineering team.";
    subinstructionText = "Format: MM/DD/YYYY (or pick a shortcut below). Press Enter to skip if unscheduled:";
    chipsList = [
      { label: "This Friday", value: "this friday" },
      { label: "Next Friday", value: "next friday" },
      { label: "In 2 Weeks", value: "2 weeks" },
      { label: "End of Month", value: "end of month" },
      { label: "Today", value: "today" },
      { label: "Skip (No date)", value: "skip", isPrimary: true },
    ];
  } else if (step === 2) {
    instructionText = "Enter the external client deadline or hard milestone date.";
    subinstructionText = "Format: MM/DD/YYYY. Press Enter or Complete to finish creating this deliverable:";
    chipsList = [];
    if (values.due) {
      chipsList.push({ label: `Same as Internal (${values.due})`, value: values.due, isPrimary: true });
    }
    chipsList.push(
      { label: "This Friday", value: "this friday" },
      { label: "Next Friday", value: "next friday" },
      { label: "In 2 Weeks", value: "2 weeks" },
      { label: "End of Month", value: "end of month" },
      { label: "Complete (No external date)", value: "skip", isPrimary: !values.due }
    );
  }

  guide.append(
    el("div", { className: "cmd-prompt-instruction", textContent: instructionText }),
    el("div", { className: "cmd-prompt-subinstruction", textContent: subinstructionText }),
    el("div", { className: "cmd-prompt-chips-label", textContent: "Quick Suggestions" })
  );

  const chipsContainer = el("div", { className: "cmd-prompt-chips" });
  chipsList.forEach((chip) => {
    const chipBtn = el("button", {
      type: "button",
      className: `cmd-prompt-chip${chip.isPrimary ? " is-primary" : ""}`,
      textContent: chip.label,
    });
    chipBtn.addEventListener("click", () => {
      advancePromptStep(chip.value);
    });
    chipsContainer.appendChild(chipBtn);
  });
  guide.appendChild(chipsContainer);

  // Preview card
  const preview = el("div", { className: "cmd-prompt-preview" });
  preview.appendChild(el("div", { className: "cmd-prompt-preview-title", textContent: "Deliverable Preview" }));

  function createPreviewRow(label, initialVal, dataKey) {
    const row = el("div", { className: "cmd-prompt-preview-row" });
    row.append(
      el("span", { className: "cmd-prompt-preview-label", textContent: label }),
      el("span", { className: "cmd-prompt-preview-val", "data-preview": dataKey, textContent: initialVal })
    );
    return row;
  }

  preview.append(
    createPreviewRow("Deliverable", values.name || "Untitled", "name"),
    createPreviewRow("Project", getProjectShortName(project), "project"),
    createPreviewRow("Internal Due", values.due || "—", "due"),
    createPreviewRow("External Due", values.hardDue || "—", "hardDue"),
    createPreviewRow("Status", "In progress", "status")
  );

  body.append(guide, preview);
  host.append(header, stepper, body);
}

// Selection ---------------------------------------------------------------

function selectDeliverableForCommands(deliverable, project, { expand = false, focus = "" } = {}) {
  const dock = ensureCommandDock();
  const same = dock.deliverable === deliverable;
  dock.deliverable = deliverable || null;
  dock.project = project || null;
  renderCommandDockItems();
  updateCommandDockContext();
  syncCommandDockSelection();

  if (dock.pendingKey && dock.deliverable) {
    const pending = dock.items.find((item) => item.key === dock.pendingKey);
    if (pending) {
      runCommandDockItem(pending);
      return;
    }
    dock.pendingKey = null;
    dock.pendingLabel = "";
    updateCommandDockContext();
  }

  if (expand) setCommandDockExpanded(true);
  if (focus) focusCommandDockGroup(focus);
  if (expand || focus) dock.input.focus({ preventScroll: true });
  else if (!same) dock.input.focus({ preventScroll: true });
}

// Picking a project selects its latest visible deliverable for commands.
function selectProjectForCommands(project, { expand = true } = {}) {
  const dock = ensureCommandDock();
  dock.project = project || null;
  dock.deliverable = null;
  dock.input.value = "";
  const latest = getCommandDockProjectDeliverables(project)[0];
  if (latest) {
    selectDeliverableForCommands(latest, project, { expand });
    return;
  }
  renderCommandDockItems();
  updateCommandDockContext();
  syncCommandDockSelection();
  const pending = dock.items.find(item => item.key === dock.pendingKey);
  if (dock.project && pending?.scope === "project") {
    runCommandDockItem(pending);
    return;
  }
  if (expand) setCommandDockExpanded(true);
  const first = dock.items.findIndex((item) => item.kind === "deliverable");
  if (first >= 0) setCommandDockActive(first);
  dock.input.focus({ preventScroll: true });
}

// Steps back: deliverable → project → nothing.
function clearCommandDockSelection() {
  if (industryActivePrompt) {
    cancelCommandDockPrompt();
    return;
  }
  const dock = ensureCommandDock();
  if (dock.deliverable) {
    dock.deliverable = null;
  } else {
    dock.project = null;
  }
  dock.input.value = "";
  renderCommandDockItems();
  updateCommandDockContext();
  syncCommandDockSelection();
}

// Re-applies the highlight after every render and drops selections whose
// records no longer exist.
function syncCommandDockSelection() {
  const dock = industryCommandDock;
  if (!dock) return;
  document
    .querySelectorAll(".reg-row.is-selected, .reg-line.is-selected, .plate-card.is-selected")
    .forEach((node) => node.classList.remove("is-selected"));
  if (dock.project && !(Array.isArray(db) && db.includes(dock.project))) {
    dock.project = null;
    dock.deliverable = null;
    renderCommandDockItems();
    updateCommandDockContext();
    return;
  }
  if (!dock.deliverable) return;
  const stillExists = getCommandDockProjectDeliverables(dock.project, { includeAll: true }).includes(dock.deliverable);
  if (!stillExists) {
    dock.deliverable = null;
    renderCommandDockItems();
    updateCommandDockContext();
    return;
  }
  const id = String(dock.deliverable.id || "").trim();
  if (!id) return;
  document
    .querySelectorAll(`[data-deliverable-id="${CSS.escape(id)}"]`)
    .forEach((node) => {
      if (node.matches(".reg-row, .reg-line, .plate-card")) node.classList.add("is-selected");
    });
}

// Ctrl+K focuses the command line from anywhere on the Projects tab.
function bindCommandDockShortcut() {
  document.addEventListener("keydown", (event) => {
    // Let fields, editors, dialogs and native menu typeahead keep their input.
    if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key.length !== 1 || !event.key.trim()) return;
    if (document.body.dataset.activeTab !== "projects") return;
    if (document.querySelector("dialog[open], [aria-modal='true'], details[open]")) return;
    const target = event.target;
    if (target?.isContentEditable || target?.closest?.(
      "input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='combobox'], [role='menu'], [role='listbox']"
    )) return;
    const dock = ensureCommandDock();
    if (!dock.root.getClientRects().length) return;
    event.preventDefault();
    // Starting from outside the input begins a fresh query, retaining context
    // until the user explicitly chooses another project.
    dock.input.value = event.key;
    setCommandDockExpanded(true);
    dock.input.focus({ preventScroll: true });
    dock.input.setSelectionRange(dock.input.value.length, dock.input.value.length);
    dock.input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  document.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "k") return;
    if (document.body.dataset.activeTab !== "projects") return;
    if (document.querySelector("dialog[open]")) return;
    const target = event.target;
    if (
      target &&
      target !== industryCommandDock?.input &&
      (target.matches?.("input, textarea, select, [contenteditable='true']") ||
        target.isContentEditable)
    ) {
      return;
    }
    event.preventDefault();
    const dock = ensureCommandDock();
    if (document.activeElement === dock.input && dock.expanded) {
      setCommandDockExpanded(false);
      dock.input.blur();
      return;
    }
    setCommandDockExpanded(true);
    dock.input.focus({ preventScroll: true });
    dock.input.select();
  });
}

// ---------------------------------------------------------------------------
// Chrome: footer and wiring
// ---------------------------------------------------------------------------

function syncDeliverableTypeOptions() {
  const menu = document.getElementById("deliverablesFilterMenu");
  if (!menu) return;
  const names = [...new Set(getAllProjectDeliverableRows()
    .map(({ deliverable }) => String(deliverable.name || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const signature = JSON.stringify(names);
  if (menu.dataset.typeOptions === signature) return;
  menu.dataset.typeOptions = signature;
  menu.querySelectorAll('[data-deliverable-type]').forEach((node) => node.remove());
  names.forEach((name) => menu.appendChild(el("button", {
    type: "button", className: "projects-filter-option", textContent: name,
    "data-filter-value": `type:${name}`, "data-deliverable-type": "true",
    role: "menuitemradio", "aria-checked": "false", tabIndex: -1,
  })));
  if (deliverablesFilter.startsWith("type:") && !names.includes(deliverablesFilter.slice(5))) {
    deliverablesFilter = "all";
  }
  syncProjectsFilterDropdowns();
}

function updateProjectsIndustryChrome() {
  syncDeliverableTypeOptions();
  const footer = document.getElementById("registerFooter");
  if (footer) footer.hidden = projectsViewMode !== "list";
  // Projects and deliverables change with every render, so the dock's target
  // list is rebuilt here (the query and expansion state are kept).
  if (industryCommandDock && !industryActivePrompt) renderCommandDockItems();
  // The board renders after this call inside render(); re-apply the highlight
  // once it has.
  requestAnimationFrame(syncCommandDockSelection);
}

document.addEventListener("DOMContentLoaded", () => {
  ensureCommandDock();
  bindCommandDockShortcut();
  const panel = document.getElementById("projects-panel");
  const toolbar = panel?.querySelector(".panel-toolbar");
  const filters = document.getElementById("projectsFilterControls");
  if (toolbar && filters) {
    const search = toolbar.querySelector(".nav-search");
    const actions = toolbar.querySelector(".toolbar-actions");
    if (search) filters.prepend(search);
    if (actions) filters.appendChild(actions);
    toolbar.hidden = true;
  }

});
