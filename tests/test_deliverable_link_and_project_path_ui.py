import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class DeliverableLinkAndProjectPathUiTests(unittest.TestCase):
    def test_project_path_root_normalization_wiring_exists(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn(
            'const PROJECT_ROOT_SEGMENT_REGEX =\n  /^(\\d{6})(?!\\d)(?:\\s*(?:[-_]\\s*)?(.*))?$/;',
            script,
        )
        self.assertIn("function normalizeWindowsPath(rawPath) {", script)
        self.assertIn("function findProjectRootPath(rawPath) {", script)
        self.assertIn("function normalizeProjectPath(rawPath) {", script)
        self.assertIn('path: normalizeProjectPath(project.path || ""),', script)
        self.assertIn('path: normalizeProjectPath(val("f_path")),', script)
        self.assertIn(
            'if (project?.path !== normalizeWindowsPath(item?.path || "")) {',
            script,
        )
        self.assertIn(
            "function normalizeProjectPathInput(pathInput, { forceProjectFields = false } = {}) {",
            script,
        )
        self.assertIn(
            "normalizeProjectPathInput(pathInput, { forceProjectFields: true })",
            script,
        )
        self.assertIn("normalizeProjectPathInput(pathInput);", script)
        self.assertIn(
            "return findWorkroomProjectRootById(projectPath) || projectPath;", script
        )

    def test_deliverable_and_work_item_attachment_wiring_exists(self):
        script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        # Cloud attachment merging was removed with cloud sync in 8fa93fa.
        for expected in (
            "function getDeliverableCardAttachments(card) {",
            "function setDeliverableCardAttachments(card, attachments) {",
            "function syncProjectAttachmentFields(project) {",
            "function syncDeliverableAttachmentFields(deliverable) {",
            "function createAttachmentTriggerIcon(size = 15) {",
            "function createAttachmentControl(descriptor = {}, options = {}) {",
            "function createWorkItemAttachmentControls({",
            'svg.setAttribute("class", "attachment-trigger-icon");',
            "function openAttachmentPanel(context) {",
            "async function requestAttachmentPanelClose(options = {}) {",
            "await addDroppedEmailToAttachmentContext(openAttachmentPanelContext, event);",
            "const attachments = getDeliverableCardAttachments(card);",
            "trigger.appendChild(createAttachmentTriggerIcon());",
            'className: "project-details-header",',
            'className: "project-details-main",',
            "projectDetailsHeader.append(projectDetailsMain, projectDetailsActions);",
            "nameCell.appendChild(projectDetailsHeader);",
            'kind: "deliverable",',
        ):
            self.assertIn(expected, script)

        self.assertNotIn("projectAttachmentInline", script)
        self.assertNotIn('className: "project-inline-attachment"', script)

    def test_unified_attachment_markup_and_styles_exist(self):
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        css = STYLES_CSS_PATH.read_text(encoding="utf-8")

        # The 2.0.0 release moved deliverable attachments out of the edit dialog.
        self.assertNotIn("Project Attachments", html)
        self.assertNotIn('id="modalProjectAttachmentHost"', html)
        self.assertNotIn('<div class="deliverable-link-control"></div>', html)
        self.assertNotIn('class="deliverable-email-slots"', html)

        for expected in (
            ".project-details-header {",
            ".project-details-main {",
            ".project-title-text {",
            ".attachment-trigger .attachment-trigger-icon {",
            ".attachment-trigger.has-attachments {",
            ".attachment-panel {",
            ".attachment-item {",
            ".attachment-action-btn {",
        ):
            self.assertIn(expected, css)

        self.assertNotIn(".modal-project-attachment-host {", css)
        self.assertNotIn(".project-inline-attachment {", css)


if __name__ == "__main__":
    unittest.main()
