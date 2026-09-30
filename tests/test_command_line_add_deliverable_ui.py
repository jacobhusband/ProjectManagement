import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDUSTRY_PROJECTS_JS = REPO_ROOT / "industry-projects.js"
INDUSTRY_CSS = REPO_ROOT / "industry.css"


class CommandLineAddDeliverableUiTests(unittest.TestCase):
    def setUp(self):
        self.js_code = INDUSTRY_PROJECTS_JS.read_text(encoding="utf-8")
        self.css_code = INDUSTRY_CSS.read_text(encoding="utf-8")

    def test_command_dock_registers_add_deliverable(self):
        self.assertIn('key: "add-deliverable"', self.js_code)
        self.assertIn('scope: "project"', self.js_code)
        self.assertIn('label: "Add Deliverable"', self.js_code)
        self.assertIn('search: "add deliverable', self.js_code)
        self.assertIn("startAddDeliverablePrompt(target.project", self.js_code)

    def test_prompt_controller_functions_exist(self):
        expected_functions = [
            "function parsePromptDate(text) {",
            "function formatPromptDate(date) {",
            'function startAddDeliverablePrompt(project, initialDescription = "") {',
            "function syncPromptInput() {",
            "function setPromptStep(stepIndex) {",
            "function advancePromptStep(forcedValue) {",
            "function completeAddDeliverablePrompt() {",
            "function cancelCommandDockPrompt(",
            "function handleCommandDockPromptKeydown(event) {",
            "function handleCommandDockPromptInput() {",
            "function renderPromptView() {",
        ]
        for fn in expected_functions:
            self.assertIn(fn, self.js_code, f"Expected function {fn} in industry-projects.js")

    def test_step_progression_and_validation(self):
        # Step 0: Description
        self.assertIn('"Add Deliverable · 1/3 Description"', self.js_code)
        self.assertIn('"Enter deliverable description (e.g. DD90) and press Enter…"', self.js_code)
        self.assertIn('"Please enter a deliverable description."', self.js_code)

        # Step 1: Soft Due Date
        self.assertIn('"Add Deliverable · 2/3 Soft Due Date"', self.js_code)
        self.assertIn('"Enter soft due date (MM/DD/YYYY) or press Enter to skip…"', self.js_code)
        self.assertIn('values.due = formatPromptDate(d);', self.js_code)

        # Step 2: Hard Due Date — must land after the soft date
        self.assertIn('"Add Deliverable · 3/3 Hard Due Date"', self.js_code)
        self.assertIn('"Enter hard due date (MM/DD/YYYY) or press Enter to complete…"', self.js_code)
        self.assertIn('values.hardDue = formatPromptDate(d);', self.js_code)
        self.assertIn("if (soft && !isEarlierDay(soft, d)) {", self.js_code)

        # "Same" moves the soft date to the hard date instead of storing it twice.
        self.assertIn(
            'values.hardDue = values.due || "";\n      values.due = "";', self.js_code
        )
        self.assertNotIn("Internal Deadline", self.js_code)
        self.assertNotIn("External Deadline", self.js_code)

    def test_date_keywords_supported(self):
        # Keywords supported in parsePromptDate
        for kw in ["today", "tomorrow", "this friday", "next friday", "next week", "2 weeks", "end of month"]:
            self.assertIn(f'"{kw}"', self.js_code)

    def test_deliverable_creation_persistence_and_selection(self):
        # Deliverable creation
        self.assertIn('typeof createDeliverable === "function"', self.js_code)
        self.assertIn("project.deliverables.push(deliverable);", self.js_code)
        self.assertIn("await save();", self.js_code)
        self.assertIn("renderProjectsPreservingExpandedDeliverables();", self.js_code)
        self.assertIn("selectDeliverableForCommands(deliverable, project", self.js_code)

    def test_keyboard_navigation_handling(self):
        # Enter advances, Escape cancels, Backspace on empty input steps back, Left/Right navigation
        self.assertIn('if (event.key === "Escape")', self.js_code)
        self.assertIn('if (event.key === "Backspace" && dock.input.value === "")', self.js_code)
        self.assertIn('if (event.key === "Enter")', self.js_code)
        self.assertIn('if (event.key === "ArrowLeft")', self.js_code)
        self.assertIn('if (event.key === "ArrowRight")', self.js_code)
        self.assertIn('if (industryActivePrompt)', self.js_code)

    def test_directional_arrows_navigation(self):
        # Main command dock handles all four arrow directions (left, right, up, down) and 2D spatial movement
        self.assertIn('function moveCommandDockSpatial(direction)', self.js_code)
        self.assertIn('moveCommandDockSpatial("down")', self.js_code)
        self.assertIn('moveCommandDockSpatial("up")', self.js_code)
        self.assertIn('moveCommandDockSpatial("right")', self.js_code)
        self.assertIn('moveCommandDockSpatial("left")', self.js_code)
        # Footer shortcuts text updated to show left and right arrows alongside up and down
        self.assertIn('"←→ ↑↓ move · ↩ run · # find a project · esc clear / collapse"', self.js_code)

    def test_css_styles_for_prompt_view(self):
        expected_selectors = [
            ".cmd-prompt-view",
            ".cmd-prompt-header",
            ".cmd-prompt-title",
            ".cmd-prompt-tag",
            ".cmd-prompt-stepper",
            ".cmd-prompt-step",
            ".cmd-prompt-step-num",
            ".cmd-prompt-guide",
            ".cmd-prompt-chips",
            ".cmd-prompt-chip",
            ".cmd-prompt-preview",
        ]
        for sel in expected_selectors:
            self.assertIn(sel, self.css_code, f"Expected CSS selector {sel} in industry.css")


if __name__ == "__main__":
    unittest.main()
