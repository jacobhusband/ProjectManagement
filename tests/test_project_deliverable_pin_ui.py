import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class ProjectDeliverablePinUiTests(unittest.TestCase):
    def test_deliverable_pin_state_is_normalized_and_preserved(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for expected in (
            "pinned: deliverable.pinned === true,",
            "pinned: seed.pinned === true,",
            "function isDeliverablePinned(deliverable) {",
            "function setDeliverablePinnedState(deliverable, nextPinned) {",
            "card.dataset.pinned = String(isDeliverablePinned(deliverable));",
            "const existingDeliverable = existingProject",
            'pinned: card.dataset.pinned === "true",',
        ):
            self.assertIn(expected, script)

    def test_deliverable_pin_button_and_card_view_bucket_use_deliverable_state(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        header_start = script.index("function createDeliverablePinButton(deliverable) {")
        header_end = script.index("let openDeliverableActionsDropdown", header_start)
        pin_button_block = script[header_start:header_end]
        card_view_start = script.index("function renderCardView(")
        card_view_end = script.index("function setProjectsViewMode(", card_view_start)
        card_view_block = script[card_view_start:card_view_end]

        for expected in (
            "titlePinned: \"Unpin deliverable\",",
            "titleUnpinned: \"Pin deliverable\",",
            "className: \"deliverable-pin-btn\",",
            "setDeliverablePinnedState(deliverable, nextPinned);",
            "renderProjectsPreservingExpandedDeliverables();",
        ):
            self.assertIn(expected, pin_button_block)

        self.assertIn(
            'label: isDeliverablePinned(deliverable) ? "Unpin deliverable" : "Pin deliverable"',
            script,
        )
        self.assertIn(
            "setDeliverablePinnedState(deliverable, !isDeliverablePinned(deliverable));",
            script,
        )
        self.assertIn(
            "const actionRow = createDeliverableCardTopActions(deliverable, project, card);",
            script,
        )
        self.assertIn(
            "card.append(header, statusSection, actionRow);",
            script,
        )
        self.assertIn("isDeliverablePinned(deliverable) ? \"is-pinned-deliverable\" : \"\"", script)
        self.assertIn("if (pinnedShown && isPinnedDeliverable) {", card_view_block)
        self.assertNotIn("pinnedShown && project.pinned", card_view_block)

    def test_pin_urgent_deliverables_pins_deliverables_not_projects(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        start = script.index("async function pinUrgentDeliverables() {")
        end = script.index("function resetCopyProjectLocallyDialogState()", start)
        block = script[start:end]

        self.assertIn("let deliverablesPinned = 0;", block)
        self.assertIn("setDeliverablePinnedState(deliverable, true);", block)
        self.assertIn("deliverablesPinned += 1;", block)
        self.assertNotIn("setProjectPinnedState(project, true, db);", block)
        self.assertNotIn("projectsPinned", block)

    def test_deliverable_pin_styles_exist(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        for expected in (
            ".deliverable-pin-btn {",
            ".deliverable-pin-btn.is-pinned {",
            "border-color: rgba(16, 185, 129, 0.35);",
        ):
            self.assertIn(expected, css)


if __name__ == "__main__":
    unittest.main()
