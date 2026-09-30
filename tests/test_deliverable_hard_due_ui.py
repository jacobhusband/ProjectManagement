import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"
INDUSTRY_JS_PATH = REPO_ROOT / "industry-projects.js"


class DeliverableHardDueUiTests(unittest.TestCase):
    @staticmethod
    def _block(text, start_marker, end_marker):
        start = text.index(start_marker)
        end = text.index(end_marker, start)
        return text[start:end]

    def test_data_model_carries_hard_due(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        normalize_block = self._block(
            script,
            "function normalizeDeliverable(",
            "function createDeliverable(",
        )
        self.assertIn('due: String(deliverable.due || "").trim(),', normalize_block)
        self.assertIn(
            'hardDue: String(deliverable.hardDue || "").trim(),', normalize_block
        )

        create_block = self._block(
            script,
            "function createDeliverable(",
            "function normalizeProject(",
        )
        self.assertIn('hardDue: seed.hardDue || "",', create_block)

    def test_due_state_helpers_expose_four_states(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for expected in (
            "function getActiveDueField(deliverable, now = new Date()) {",
            "function getEffectiveDueStr(deliverable, now = new Date()) {",
            "function getHardDueStr(deliverable) {",
            "function deliverableDueState(deliverable) {",
            "function isDeliverableHardDueMissed(deliverable) {",
        ):
            self.assertIn(expected, script)

        state_block = self._block(
            script,
            "function deliverableDueState(",
            "function isDeliverableHardDueMissed(",
        )
        # A missed hard deadline escalates above plain overdue, but never for
        # work that is already finished.
        self.assertIn('return "critical";', state_block)
        self.assertIn("!isFinished(deliverable)", state_block)
        self.assertIn("return dueState(getEffectiveDueStr(deliverable));", state_block)

        active_block = self._block(
            script,
            "function getActiveDueField(",
            "function isEarlierDay(",
        )
        # Soft date shows until it passes, then the hard date takes over; a soft
        # date that is not before the hard date never shows.
        self.assertIn('if (!soft) return hard ? "hardDue" : "";', active_block)
        self.assertIn('if (!hard) return "due";', active_block)
        self.assertIn(
            'if (!softDate || !isEarlierDay(softDate, hardDate)) return "hardDue";',
            active_block,
        )
        self.assertIn(
            'return isEarlierDay(softDate, now) ? "hardDue" : "due";', active_block
        )

        effective_block = self._block(
            script,
            "function getEffectiveDueStr(",
            "function getHardDueStr(",
        )
        self.assertIn("getActiveDueField(deliverable, now)", effective_block)

    def test_scheduling_logic_uses_effective_due_date(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for expected in (
            # Sorting
            "function compareDeliverablesByDue(a, b) {\n  const da = parseDueStr(getEffectiveDueStr(a));",
            # Timeframe filter
            "function matchesDueFilter(deliverable, filter) {\n  if (filter === \"all\") return true;\n  if (filter === \"attention\") return deliverableNeedsAttention(deliverable);\n  const d = parseDueStr(getEffectiveDueStr(deliverable));",
            # Week / kanban view
            "function deliverableDueInWeek(deliverable, weekStart) {\n  const d = parseDueStr(getEffectiveDueStr(deliverable));",
            "function deliverableIsOverdueIncomplete(deliverable, weekStart) {\n  const d = parseDueStr(getEffectiveDueStr(deliverable));",
            # Project rows
            "dueDate: parseDueStr(getEffectiveDueStr(deliverable)),",
            "isHardDueMissed: isDeliverableHardDueMissed(deliverable),",
        ):
            self.assertIn(expected, script)

    def test_missed_hard_deadline_sorts_above_plain_overdue(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        compare_block = self._block(
            script,
            "function compareProjectDeliverableRows(",
            "function sortProjectDeliverableRows(",
        )
        self.assertIn("const aHardMissed = !!a?.isHardDueMissed;", compare_block)
        self.assertIn("const bHardMissed = !!b?.isHardDueMissed;", compare_block)
        self.assertIn(
            "if (aHardMissed !== bHardMissed) return aHardMissed ? -1 : 1;",
            compare_block,
        )

    def test_pin_urgent_deliverables_catches_hard_deadlines(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        pin_block = self._block(
            script,
            "async function pinUrgentDeliverables(",
            "function resetCopyProjectLocallyDialogState(",
        )
        self.assertIn("const hardDueStr = getHardDueStr(deliverable);", pin_block)
        self.assertIn(
            'const hardUrgent = !!parseDueStr(hardDueStr) && dueState(hardDueStr) !== "ok";',
            pin_block,
        )
        self.assertIn("if (!hardUrgent) {", pin_block)

    def test_deliverable_card_renders_one_tagged_due_badge(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("function createDeliverableDueBadges(deliverable, project) {", script)
        badges_block = self._block(
            script,
            "function createDeliverableDueBadges(",
            "function createExpandToggle(",
        )
        self.assertIn("const field = getActiveDueField(deliverable);", badges_block)
        self.assertIn("if (!field) return [];", badges_block)
        self.assertNotIn('field: "hardDue",', badges_block)

        state_block = self._block(
            script,
            "function getDueBadgeStateClass(",
            "function createDeliverableDueBadge(",
        )
        self.assertIn(
            'return isDeliverableHardDueMissed(deliverable) ? "hard critical" : "hard";',
            state_block,
        )

        badge_block = self._block(
            script,
            "function createDeliverableDueBadge(",
            "function createDeliverableDueBadges(",
        )
        # The Soft / Hard tag is what tells the user which date is showing.
        self.assertIn(
            "badge.append(createDueKindTag(field), document.createTextNode(text));",
            badge_block,
        )
        self.assertIn("describeDeliverableDue(deliverable)", badge_block)
        self.assertIn(
            'const DUE_FIELD_LABELS = Object.freeze({ due: "Soft", hardDue: "Hard" });',
            script,
        )

    def test_badge_calendar_can_set_either_date(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        calendar_block = self._block(
            script,
            "function showCalendarForDeliverableBadge(",
            "function renderInlineCalendar(",
        )
        # Opens on the shown date, with a Soft / Hard switch and a Clear button.
        self.assertIn(
            'let activeField = field || getActiveDueField(deliverable) || "due";',
            calendar_block,
        )
        self.assertIn("className: 'calendar-due-kind-switch',", calendar_block)
        self.assertIn('["due", "hardDue"].forEach((key) => {', calendar_block)
        self.assertIn('clearBtn.onclick = () => commit("");', calendar_block)
        # Every write goes through the soft-before-hard guard.
        self.assertIn(
            "if (!applyDeliverableDueDate(deliverable, activeField, value)) return;",
            calendar_block,
        )
        self.assertNotIn("deliverable[field] = formatDueDateShort(", calendar_block)

        apply_block = self._block(
            script,
            "function applyDeliverableDueDate(",
            "function deliverableDueState(",
        )
        self.assertIn('deliverable.due = "";', apply_block)
        self.assertIn("The soft due date must be before the hard due date", apply_block)

    def test_edit_modal_exposes_a_hard_deadline_input(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('<label class="label">Soft Due Date</label>', html)
        self.assertIn('<label class="label">Hard Due Date</label>', html)
        self.assertIn('<input class="d-hard-due" placeholder="MM/DD/YYYY" />', html)
        self.assertIn("Earlier target that can slip. Shows until it passes.", html)
        self.assertIn("Must-finish date. Shows once the soft date passes.", html)
        self.assertNotIn("Internal Due Date", html)

    def test_modal_populates_validates_and_saves_hard_due(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn(
            'card.querySelector(".d-hard-due").value = deliverable.hardDue || "";',
            script,
        )
        self.assertIn(
            "const dateInput = wrapper.querySelector('.d-due, .d-hard-due');", script
        )
        self.assertIn(
            "const inputs = document.querySelectorAll('.d-due, .d-hard-due');", script
        )
        self.assertIn(
            "document.querySelector('.d-due.input-error, .d-hard-due.input-error')",
            script,
        )

        read_form_block = self._block(
            script,
            "function readForm(",
            "function addRefRowFrom(",
        )
        self.assertIn(
            'const hardDue = card.querySelector(".d-hard-due").value.trim();',
            read_form_block,
        )
        self.assertIn("hardDue,", read_form_block)

    def test_soft_date_not_before_hard_date_blocks_the_save(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        order_block = self._block(
            script,
            "function validateDeliverableDateOrder(",
            "function validateAllDueDates(",
        )
        self.assertIn(
            "if (!due || !hardDue || isEarlierDay(due, hardDue)) return true;",
            order_block,
        )
        self.assertIn("dueInput.classList.add('input-error');", order_block)
        self.assertIn("'Soft due date must be before the hard due date'", order_block)
        self.assertIn("return false;", order_block)

        validate_all_block = self._block(
            script,
            "function validateAllDueDates(",
            "function showCalendarForInput(",
        )
        self.assertIn("if (!validateDeliverableDateOrder(card)) {", validate_all_block)

    def test_modal_hides_a_soft_date_on_the_same_day_as_the_hard_date(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'card.querySelector(".d-due").value = redundantSoft ? "" : deliverable.due || "";',
            script,
        )

    def test_register_shows_one_due_column(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        industry = INDUSTRY_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('<th class="reg-th">Due</th>', html)
        self.assertNotIn('<th class="reg-th">Internal</th>', html)
        self.assertNotIn('<th class="reg-th">External</th>', html)

        self.assertIn(
            "function createRegisterDueField(deliverable, project, state) {", industry
        )
        self.assertIn("return [code, due, statusCol, actions];", industry)
        self.assertNotIn('"Internal"', industry)
        self.assertNotIn('"External"', industry)

    def test_hard_and_critical_badge_styles_exist(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".deliverable-due-badge.hard {", css)
        self.assertIn(".deliverable-due-badge.hard.critical,", css)
        self.assertIn(".deliverable-due-badge.critical {", css)
        self.assertIn(".deliverable-summary-due {", css)
        self.assertIn(".due-kind--soft {", css)
        self.assertIn(".due-kind--hard {", css)
        self.assertIn(".calendar-due-kind-switch {", css)

    def test_note_level_due_date_ui_stays_removed(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertNotIn("function createNoteDueDateControl(", script)
        self.assertNotIn(".note-due-badge {", css)


if __name__ == "__main__":
    unittest.main()
