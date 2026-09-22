import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML_PATH = REPO_ROOT / "index.html"
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class ProjectFiltersUiTests(unittest.TestCase):
    def test_project_filter_markup_uses_custom_dropdowns_and_settings_toggles(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        projects_filters_start = html.index(
            '<div class="filter-controls projects-filter-controls" id="projectsFilterControls">'
        )
        table_start = html.index('<table class="table projects-table">')
        projects_filters_block = html[projects_filters_start:table_start]
        settings_block_start = html.index(
            '<div class="setting-label">Separate Incomplete and Complete Deliverables</div>'
        )
        settings_block_end = html.index("<!-- Danger Zone -->")
        settings_block = html[settings_block_start:settings_block_end]

        self.assertIn('data-filter-dropdown="timeframe"', html)
        self.assertIn('id="timeframeFilterTrigger"', html)
        self.assertIn('id="timeframeFilterMenu"', html)
        self.assertIn('data-filter-value="future"', html)
        self.assertIn('data-filter-dropdown="status"', html)
        self.assertIn('id="statusFilterTrigger"', html)
        self.assertIn('id="statusFilterMenu"', html)
        self.assertIn('data-filter-value="Pending Review"', html)
        self.assertIn('data-filter-dropdown="deliverables"', html)
        self.assertIn('id="deliverablesFilterTrigger"', html)
        self.assertIn('id="deliverablesFilterMenu"', html)
        self.assertNotIn('data-filter-value="active"', html)
        self.assertNotIn("Show only active deliverables", html)
        self.assertIn("Show all deliverables", html)
        self.assertIn("Show all incomplete deliverables", html)
        self.assertIn('role="menuitemradio"', html)
        self.assertNotIn('id="timeframeFilterSelect"', html)
        self.assertNotIn('id="statusFilterSelect"', html)
        self.assertNotIn('id="toggleNonPrimaryBtn"', html)
        self.assertNotIn('data-filter-value="primary"', html)
        self.assertNotIn('id="separateDeliverableCompletionToggle"', projects_filters_block)
        self.assertNotIn('id="groupDeliverablesByProjectToggle"', projects_filters_block)
        self.assertNotIn('id="settings_autoPrimary"', html)
        self.assertIn(
            'id="settings_separateDeliverableCompletionGroups"', settings_block
        )
        self.assertIn('Separate Incomplete and Complete Deliverables', settings_block)
        # "Group Deliverables by Project" was retired in 17f6a90 and is always off.
        self.assertNotIn('id="settings_groupDeliverablesByProject"', settings_block)
        self.assertNotIn('class="projects-view-controls"', html)

    def test_project_filter_script_wiring_exists(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        user_settings_start = script.index("let userSettings = {")
        user_settings_end = script.index("const DEFAULT_GOOGLE_AUTH_STATE = {")
        user_settings_block = script[user_settings_start:user_settings_end]
        load_settings_start = script.index("async function loadUserSettings() {")
        load_settings_end = script.index("function setCheckboxValue(id, value) {")
        load_settings_block = script[load_settings_start:load_settings_end]
        populate_start = script.index("async function populateSettingsModal() {")
        populate_end = script.index("async function populateAutocadSelectModal() {")
        populate_block = script[populate_start:populate_end]
        save_start = script.index("async function saveUserSettings() {")
        save_end = script.index("const debouncedSaveUserSettings = debounce(saveUserSettings, 500);")
        save_block = script[save_start:save_end]
        comparator_start = script.index(
            "function compareProjectListSortBuckets(a, b, projectListContextMap = null) {"
        )
        render_context_start = script.index("function getProjectListRenderContext(project) {")
        comparator_block = script[comparator_start:render_context_start]
        deliverable_row_comparator_start = script.index(
            "function compareProjectDeliverableRows(a, b) {"
        )
        deliverable_row_sort_start = script.index("function sortProjectDeliverableRows(items) {")
        deliverable_row_comparator_block = script[
            deliverable_row_comparator_start:deliverable_row_sort_start
        ]
        settings_handlers_start = script.index('document.getElementById("settings_userName").oninput = (e) => {')
        settings_handlers_end = script.index(
            '      "autoDetectPaperSize",',
            settings_handlers_start,
        )
        settings_handlers_block = script[settings_handlers_start:settings_handlers_end]

        self.assertIn('let currentSort = { key: "due", dir: "asc" };', script)
        self.assertIn('let separateDeliverableCompletionGroups = true;', script)
        self.assertIn('let groupDeliverablesByProject = false;', script)
        self.assertIn("function syncProjectViewPreferencesFromSettings() {", script)
        self.assertIn(
            "separateDeliverableCompletionGroups =\n    userSettings.separateDeliverableCompletionGroups !== false;",
            script,
        )
        # "Group Deliverables by Project" was retired in 17f6a90: it is forced off on
        # load and whenever view preferences sync from settings.
        self.assertIn(
            "  groupDeliverablesByProject = false;\n  userSettings.groupDeliverablesByProject = false;",
            script,
        )
        self.assertIn("separateDeliverableCompletionGroups: true,", user_settings_block)
        self.assertIn("groupDeliverablesByProject: false,", user_settings_block)
        self.assertIn(
            "userSettings.separateDeliverableCompletionGroups =\n      userSettings.separateDeliverableCompletionGroups !== false;",
            load_settings_block,
        )
        self.assertIn("userSettings.groupDeliverablesByProject = false;", load_settings_block)
        self.assertIn("syncProjectViewPreferencesFromSettings();", load_settings_block)
        self.assertIn(
            '"settings_separateDeliverableCompletionGroups"',
            populate_block,
        )
        self.assertIn(
            "userSettings.separateDeliverableCompletionGroups",
            populate_block,
        )
        self.assertIn(
            '"settings_separateDeliverableCompletionGroups"',
            save_block,
        )
        self.assertIn(
            "userSettings.separateDeliverableCompletionGroups =",
            save_block,
        )
        self.assertIn("syncProjectViewPreferencesFromSettings();", save_block)
        self.assertIn(
            '"settings_separateDeliverableCompletionGroups"',
            settings_handlers_block,
        )
        self.assertIn(
            "userSettings.separateDeliverableCompletionGroups = e.target.checked;",
            settings_handlers_block,
        )
        self.assertIn("syncProjectViewPreferencesFromSettings();", settings_handlers_block)
        self.assertIn("render();", settings_handlers_block)
        self.assertIn("debouncedSaveUserSettings();", settings_handlers_block)
        self.assertIn("function syncProjectsFilterDropdowns() {", script)
        self.assertIn("function setProjectsFilterDropdownState(", script)
        self.assertIn("function moveProjectsFilterOptionFocus(", script)
        self.assertIn("function matchesProjectStatusFilter(deliverable, filter) {", script)
        self.assertIn("function matchesProjectDeliverablesFilter(", script)
        self.assertIn("function getProjectListRenderContext(project) {", script)
        self.assertIn("function getProjectListPriorityMeta(project) {", script)
        self.assertIn("function getProjectListPriorityDeliverable(project) {", script)
        self.assertIn("function shouldSortCompletedProjectsLast() {", script)
        self.assertIn(
            "function compareProjectListSortBuckets(a, b, projectListContextMap = null) {",
            script,
        )
        self.assertIn(
            "function buildProjectDeliverableRowEntries(items, projectListContextMap = null) {",
            script,
        )
        self.assertIn("function getProjectDeliverableRowSortBucket(row) {", script)
        self.assertIn("function compareProjectDeliverableRows(a, b) {", script)
        self.assertIn("function sortProjectDeliverableRows(items) {", script)
        self.assertIn(
            "function buildProjectTableRow(project, projectIndex, rowTemplate) {",
            script,
        )
        self.assertIn("function renderGroupedProjectRows({", script)
        self.assertIn("function renderUngroupedDeliverableRows({", script)
        self.assertIn("function buildProjectTimeframeNote(", script)
        self.assertIn(
            'document.querySelectorAll(".projects-filter-dropdown").forEach((dropdown) => {',
            script,
        )
        self.assertIn('const filterKey = dropdown.dataset.filterDropdown;', script)
        self.assertIn('if (filterKey === "timeframe") return dueFilter || "all";', script)
        self.assertIn('if (filterKey === "status") return statusFilter || "all";', script)
        self.assertIn(
            'if (filterKey === "deliverables") return deliverablesFilter || "all";',
            script,
        )
        self.assertIn('dueFilter = value;', script)
        self.assertIn('currentSort.dir = value === "all" ? "asc" : "desc";', script)
        self.assertIn('statusFilter = value;', script)
        self.assertIn('deliverablesFilter = value;', script)
        self.assertIn("const projectListContextMap = new Map();", script)
        self.assertIn(
            'if (projectListContext && "anchorDueDate" in projectListContext) {',
            script,
        )
        self.assertIn("separateDeliverableCompletionGroups &&", script)
        self.assertIn('currentSort.key === "due"', script)
        self.assertIn('dueFilter === "all"', script)
        self.assertIn('statusFilter === "all"', script)
        self.assertIn("const projectListPriority = getProjectListPriorityMeta(project);", script)
        self.assertIn(
            "const priorityDeliverable = projectListPriority.priorityDeliverable;",
            script,
        )
        self.assertIn("const overviewDeliverables = getOverviewDeliverables(project);", script)
        self.assertIn(
            "hasIncompleteWork: projectListPriority.hasIncompleteWork,",
            script,
        )
        self.assertIn("sortBucket: projectListPriority.sortBucket,", script)
        self.assertIn("sortDueDate: projectListPriority.sortDueDate,", script)
        self.assertIn("fallbackDueDate: projectListPriority.fallbackDueDate,", script)
        self.assertIn("const visibleDeliverables = projectListContext.visibleDeliverables;", script)
        self.assertIn(
            "const bucketDiff = compareProjectListSortBuckets(a, b, projectListContextMap);",
            script,
        )
        self.assertIn("if (bucketDiff) return bucketDiff;", script)
        self.assertIn("let completeProjectsSectionShown = false;", script)
        self.assertIn("let lastCompleteWeekKey = null;", script)
        self.assertIn("const isCompleteOnlyProject =", script)
        self.assertIn(
            "shouldSortCompletedProjectsLast() && !projectListContext.hasIncompleteWork;",
            script,
        )
        self.assertIn('appendSectionSeparator("Complete Projects");', script)
        self.assertIn('appendSectionSeparator("Complete Deliverables");', script)
        self.assertIn("if (!completeProjectsSectionShown) {", script)
        self.assertIn("completeProjectsSectionShown = true;", script)
        self.assertIn("if (isCompleteOnlyProject) {", script)
        self.assertIn(
            "if (lastCompleteWeekKey === null || weekKey !== lastCompleteWeekKey) {",
            script,
        )
        self.assertIn("lastCompleteWeekKey = weekKey;", script)
        self.assertIn("if (lastWeekKey === null || weekKey !== lastWeekKey) {", script)
        self.assertIn("lastWeekKey = weekKey;", script)
        self.assertIn('appendSectionSeparator("Pinned Deliverables");', script)
        self.assertNotIn('appendSectionSeparator("Pinned Projects");', script)
        self.assertIn("const deliverableRows = buildProjectDeliverableRowEntries(", script)
        self.assertIn("sortProjectDeliverableRows(deliverableRows);", script)
        self.assertIn("const isSeparatedCompleteDeliverable =", script)
        self.assertIn("shouldSortCompletedProjectsLast() &&", script)
        self.assertIn(
            'const emptyStateEntityLabel = groupDeliverablesByProject',
            script,
        )
        self.assertIn('? "projects"', script)
        self.assertIn(': "deliverables";', script)
        self.assertIn(
            '"Create a new project with a deliverable to get started."',
            script,
        )
        self.assertIn("if (groupDeliverablesByProject) {", script)
        self.assertIn("renderGroupedProjectRows({", script)
        self.assertIn("renderUngroupedDeliverableRows({", script)
        self.assertIn("const da = aContext?.fallbackDueDate || null;", comparator_block)
        self.assertIn("const dbb = bContext?.fallbackDueDate || null;", comparator_block)
        self.assertIn("return dbb - da;", comparator_block)
        self.assertNotIn("return da - dbb;", comparator_block)
        self.assertIn("const sortBucketDiff =", deliverable_row_comparator_block)
        self.assertIn(
            "if (!separateDeliverableCompletionGroups) {",
            deliverable_row_comparator_block,
        )
        self.assertIn(
            "const mixedDueDiff = compareDueDateValues(",
            deliverable_row_comparator_block,
        )
        self.assertIn(
            "if (mixedDueDiff) return mixedDueDiff;",
            deliverable_row_comparator_block,
        )
        self.assertIn('"desc"', deliverable_row_comparator_block)
        self.assertIn(
            "getProjectDeliverableRowSortBucket(a) - getProjectDeliverableRowSortBucket(b);",
            deliverable_row_comparator_block,
        )
        self.assertIn(
            "getProjectDeliverableRowSortBucket(a) >= 2",
            deliverable_row_comparator_block,
        )
        self.assertIn("compareDueDateValues(", deliverable_row_comparator_block)
        self.assertIn(": projectListPriority.sortDueDate", script)
        self.assertIn(": projectListPriority.fallbackDueDate,", script)
        self.assertIn("The highest-priority deliverable is outside this timeframe.", script)
        self.assertIn('statusFilter !== "all" || deliverablesFilter !== "all"', script)
        self.assertNotIn("function syncProjectsViewToggles() {", script)
        self.assertNotIn('"separateDeliverableCompletionToggle"', script)
        self.assertNotIn('"groupDeliverablesByProjectToggle"', script)
        self.assertNotIn("toggleNonPrimaryBtn", script)
        self.assertNotIn('return deliverablesFilter || "primary";', script)
        self.assertNotIn('return deliverablesFilter || "active";', script)

    def test_project_filter_styles_keep_dropdown_classes_without_inline_toggle_styles(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".projects-filter-controls {", css)
        self.assertIn(".projects-filter-row {", css)
        self.assertIn(".projects-filter-group {", css)
        self.assertIn(".projects-filter-dropdown {", css)
        self.assertIn(
            '.projects-filter-dropdown[data-filter-dropdown="deliverables"] {',
            css,
        )
        self.assertIn(".projects-filter-trigger {", css)
        self.assertIn(".projects-filter-menu {", css)
        self.assertIn(".projects-filter-option {", css)
        self.assertIn(".projects-filter-option.is-selected {", css)
        self.assertIn(".projects-filter-dropdown.open .projects-filter-chevron {", css)
        self.assertIn(".project-timeframe-note {", css)
        self.assertNotIn(".projects-filter-select {", css)
        self.assertNotIn(".projects-filter-toggle-group {", css)
        self.assertNotIn(".projects-inline-toggle {", css)
        self.assertNotIn(".projects-inline-toggle-text {", css)
        self.assertNotIn(".projects-view-controls {", css)


if __name__ == "__main__":
    unittest.main()
