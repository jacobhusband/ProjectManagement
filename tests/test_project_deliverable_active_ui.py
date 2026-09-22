import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML_PATH = REPO_ROOT / "index.html"
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class ProjectDeliverableActiveFeatureRemovalTests(unittest.TestCase):
    def test_active_controls_and_copy_are_removed(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertNotIn('class="d-active"', html)
        self.assertNotIn("Auto-Set Latest as Active", html)
        self.assertNotIn('id="settings_autoPrimary"', html)
        self.assertNotIn('data-filter-value="active"', html)
        self.assertNotIn("Show only active deliverables", html)
        self.assertIn("Show all deliverables", html)
        self.assertIn("Show all incomplete deliverables", html)

    def test_active_state_wiring_is_removed_and_legacy_data_is_cleaned(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for removed in (
            "function isDeliverableActive(",
            "function getProjectActiveDeliverables(",
            "function getActiveAnchorDeliverable(",
            "function syncProjectActiveDeliverables(",
            "function autoSetPrimary(",
            "ensureModalProjectHasActiveDeliverable",
            ".d-active",
            "deliverable.active",
            "hasIncompleteActiveWork",
            "activeAnchorDeliverable",
            'return deliverablesFilter || "active";',
        ):
            self.assertNotIn(removed, script)

        # Local migration strips legacy fields; the cloud-side copies of this cleanup
        # were removed with cloud sync in 8fa93fa.
        self.assertIn("function projectHasLegacyActiveState(project) {", script)
        self.assertIn("delete out.overviewDeliverableId;", script)
        self.assertIn('let deliverablesFilter = "all";', script)
        self.assertIn('return deliverablesFilter || "all";', script)

    def test_project_priority_uses_incomplete_work_without_selection_state(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        priority_start = script.index("function getProjectListPriorityMeta(project) {")
        priority_end = script.index(
            "function getProjectListPriorityDeliverable(project) {", priority_start
        )
        priority_block = script[priority_start:priority_end]

        self.assertIn(
            "const priorityDeliverable = getEarliestIncompleteDeliverable(project);",
            priority_block,
        )
        self.assertIn("hasIncompleteWork: false,", priority_block)
        self.assertIn("hasIncompleteWork: true,", priority_block)
        self.assertNotIn("active", priority_block.lower())

    def test_edit_modal_sorts_latest_due_first_and_expands_first_card(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        fill_form_start = script.index("function fillForm(project) {")
        fill_form_end = script.index("function getDeliverableCardEmailRefs", fill_form_start)
        fill_form_block = script[fill_form_start:fill_form_end]

        self.assertIn(".sort(compareDeliverablesByDueDesc);", fill_form_block)
        self.assertIn("sortedDeliverables.forEach((deliverable, index) =>", fill_form_block)
        self.assertIn("startExpanded: index === 0,", fill_form_block)
        self.assertNotIn("active", fill_form_block.lower())

    def test_active_card_highlight_styles_are_removed(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertNotIn(".deliverable-card.is-primary", css)
        self.assertNotIn(".deliverable-card-new.is-primary", css)
        self.assertNotIn(".deliverable-star", css)


if __name__ == "__main__":
    unittest.main()
