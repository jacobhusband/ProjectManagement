import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class DeliverableToolDropdownUiTests(unittest.TestCase):
    def test_shared_tool_registry_has_category_field_per_entry(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for expected in (
            "const SHARED_TOOL_LAUNCH_REGISTRY = Object.freeze([",
            'id: "toolCopyProjectLocally"',
            'menuLabel: "Work Locally"',
            'id: "toolPublishDwgs"',
            'menuLabel: "Publish"',
            'id: "toolManageLayers"',
            'menuLabel: "Freeze / Thaw"',
            'id: "toolCleanXrefs"',
            'menuLabel: "New Backgrounds"',
            'id: "toolCreateNarrativeTemplate"',
            'menuLabel: "Narrative"',
            'id: "toolCreatePlanCheckTemplate"',
            'menuLabel: "Plan Check"',
            'id: "toolWireSizer"',
            'id: "toolCircuitBreaker"',
            'id: "toolBackupDrawings"',
            'menuLabel: "Archive"',
            'id: "toolLightingSchedule"',
            "isReady: false,",
            'category: "general",',
            'category: "electrical",',
            'category: "templates",',
            "function getReadySharedToolLaunchEntries() {",
            "function getDeliverableToolMenuEntries() {",
            "function getDeliverableToolMenuEntriesByCategory() {",
            "const DELIVERABLE_TOOL_CATEGORIES = Object.freeze([",
            '{ key: "general", label: "General" },',
            '{ key: "electrical", label: "Electrical" },',
            '{ key: "templates", label: "Templates" },',
            "function buildProjectsTabToolLaunchContext(project, deliverable) {",
            'source: "projects-tab",',
            "function launchSharedToolCard(toolId, launchContext = null) {",
        ):
            self.assertIn(expected, text)

    def test_card_view_icon_action_wiring_exists(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for expected in (
            "function createDeliverableCardTopActions(deliverable, project, card) {",
            "function createDeliverableCardActionButton({",
            "function createDeliverableAttachmentAction(deliverable, project, card) {",
            'className: "deliverable-card-action-row"',
            'className: "deliverable-card-action-group deliverable-card-action-group-left"',
            'className: "deliverable-card-action-group deliverable-card-action-group-right"',
            "const statusDropdown = createStatusDropdown(deliverable, project, card);",
            'statusDropdown.classList.add("deliverable-card-status-action");',
            "const toolDropdown = createDeliverableToolDropdown(deliverable, project, card);",
            'toolDropdown.classList.add("deliverable-card-tool-action");',
            "leftActions.append(statusDropdown, toolDropdown, quickAccessDropdown);",
            "rightActions.appendChild(createDeliverableActionsDropdown(deliverable, project, card));",
            "actions.append(leftActions, rightActions);",
            "openEdit(projectIndex)",
            "removeDeliverable(project, deliverable)",
            "openAttachmentPanel(attachmentContext)",
            "async function handleDeliverableActionsDrop(context, event) {",
            "await handleDeliverableActionsDrop(attachmentContext, event);",
            "updateAttachmentTriggerState(button, getAttachments());",
            "isSupportedEmailFile",
            "const actionRow = createDeliverableCardTopActions(deliverable, project, card);",
            "card.append(header, statusSection, actionRow);",
            "card.insertBefore(projectMeta, card.firstChild);",
        ):
            self.assertIn(expected, text)

        top_actions_start = text.index("function createDeliverableCardTopActions(")
        top_actions_end = text.index("let openDeliverableActionsDropdown = null;", top_actions_start)
        top_actions_block = text[top_actions_start:top_actions_end]
        self.assertIn("leftActions.append(statusDropdown, toolDropdown, quickAccessDropdown);", top_actions_block)
        more_start = text.index("function createDeliverableActionsDropdown(")
        more_end = text.index("function createCardHeader(", more_start)
        more_block = text[more_start:more_end]
        self.assertIn('label: "Delete deliverable"', more_block)
        self.assertIn("removeDeliverable(project, deliverable)", more_block)
        self.assertIn('label: "Edit Project"', more_block)
        self.assertNotIn("removeProject(projectIndex)", more_block)
        self.assertNotIn("removeDeliverable(", top_actions_block)
        # The inline attachment and open-project-page buttons have been removed.
        self.assertNotIn("attachmentBtn", top_actions_block)
        self.assertNotIn("createDeliverableAttachmentAction", top_actions_block)
        self.assertNotIn("deliverable-card-open-project-page-action", top_actions_block)
        # The project notes entry point remains.
        self.assertIn("deliverable-card-open-page-action", top_actions_block)
        self.assertNotIn("createExpandToggle(card)", top_actions_block)
        self.assertNotIn("deliverable-card-expand-action", top_actions_block)

        header_start = text.index("function createCardHeader(")
        header_end = text.index("function createExpandToggle(", header_start)
        header_block = text[header_start:header_end]
        self.assertNotIn("createDeliverableActionsDropdown", header_block)
        self.assertNotIn("actionsDropdown", header_block)
        self.assertNotIn("createDeliverableCardTopActions", header_block)

        self.assertNotIn("function createDeliverableCardBottomActions(", text)
        self.assertNotIn("const bottomActions = createDeliverableCardBottomActions(", text)
        self.assertNotIn("deliverable-card-bottom-actions", text)

    def test_card_view_icon_actions_close_other_popovers(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for expected in (
            "function closeDeliverableCardActionOverlays() {",
            "closeOpenDeliverableToolDropdown();",
            "closeOpenDeliverableStatusDropdowns();",
            "closeOpenDeliverableActionsDropdown();",
            "if (openAttachmentPanelContext) {",
            "void requestAttachmentPanelClose();",
        ):
            self.assertIn(expected, text)

    def test_card_view_icon_action_styles_exist(self):
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        for expected in (
            ".deliverable-card-action-row {",
            ".deliverable-card-action-group {",
            ".deliverable-card-action-group-left {",
            ".deliverable-card-action-group-right {",
            ".deliverable-card-action-btn,",
            ".deliverable-card-action-btn:hover,",
            ".deliverable-card-action-btn.is-pinned {",
            ".deliverable-card-action-btn.danger {",
            ".deliverable-card-action-btn.is-dragover {",
            ".deliverable-card-action-btn.has-attachments::after {",
            ".deliverable-card-action-row .deliverable-status-trigger,",
            ".deliverable-card-action-row .deliverable-tool-menu {",
        ):
            self.assertIn(expected, css)

    def test_deliverable_tool_dropdown_icons_and_styles(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        for expected in (
            "function createSharedToolIcon(entryOrId, size = 14) {",
            'svg.setAttribute("class", "deliverable-tool-option-icon");',
            "const icon = createSharedToolIcon(entry, 14);",
            'className: "deliverable-tool-option-label"',
            "option.append(icon, label);",
        ):
            self.assertIn(expected, text)

        for expected in (
            ".deliverable-tool-option {",
            "display: flex;",
            "align-items: center;",
            ".deliverable-tool-option-icon {",
            "width: 14px;",
            "height: 14px;",
            ".deliverable-tool-option-label {",
        ):
            self.assertIn(expected, css)


    def test_card_view_dropdown_positioning_and_visible_board_bounds(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        for expected in (
            "function positionDropdownMenuInCardView(dropdown, isOpen) {",
            'menu.style.maxHeight = "";',
            'menu.style.overflowY = "";',
            'const cardView = dropdown.closest(".projects-card-view");',
            "const cardViewRect = cardView.getBoundingClientRect();",
            "const minLeft = Math.max(margin, cardViewRect.left + margin);",
            "let minTop = Math.max(margin, cardViewRect.top + margin);",
            "const maxBottom = Math.min(viewportH - margin, cardViewRect.bottom - margin);",
            '.querySelector(":scope > .kanban-column__header");',
            "headerRect.bottom + gap",
            "const spaceBelow = Math.max(0, maxBottom - (triggerRect.bottom + gap));",
            "const spaceAbove = Math.max(0, (triggerRect.top - gap) - minTop);",
            "menu.style.maxHeight = `${maxHeight}px`;",
            'menu.style.overflowY = "auto";',
            'menu.style.overscrollBehavior = "contain";',
        ):
            self.assertIn(expected, text)

        for expected in (
            ".deliverable-tool-menu {",
            "max-height: min(480px, calc(100vh - 24px));",
            "overflow-y: auto;",
            "overscroll-behavior: contain;",
            ".deliverable-tool-menu::-webkit-scrollbar",
            ".kanban-column__cards.dropdown-open {",
            "position: relative;",
            "z-index: 10;",
            ".deliverable-card-new.deliverable-menu-open {",
            "z-index: 1000;",
        ):
            self.assertIn(expected, css)


if __name__ == "__main__":
    unittest.main()

