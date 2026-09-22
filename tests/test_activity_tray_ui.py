import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML_PATH = REPO_ROOT / "index.html"
SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


class ActivityTrayUiTests(unittest.TestCase):
    def test_activity_tray_markup_exists(self):
        text = INDEX_HTML_PATH.read_text(encoding="utf-8")

        self.assertIn('id="activityTray"', text)
        self.assertIn('id="activityTrayToggle"', text)
        self.assertIn('id="activityTrayCounts"', text)
        self.assertIn('id="activityTrayBody"', text)
        self.assertIn('id="activityTrayEmpty"', text)
        self.assertIn('id="activityTrayList"', text)
        self.assertIn('id="activityTrayClearAll"', text)
        self.assertIn('class="activity-tray-header"', text)
        self.assertIn("Activity", text)
        self.assertIn("No activity yet.", text)
        self.assertIn("Clear Completed", text)

    def test_activity_tray_styles_exist(self):
        text = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".activity-tray", text)
        self.assertIn(".activity-tray.is-collapsed .activity-tray-body", text)
        self.assertIn(".activity-card", text)
        self.assertIn(".activity-card-project", text)
        self.assertIn(".activity-card-timing", text)
        self.assertIn(".activity-card-duration", text)
        self.assertIn(".activity-card-progress-bar", text)
        self.assertIn(".activity-card-action.accept", text)
        self.assertIn(".activity-card-action.rerun", text)
        self.assertIn(".activity-card-action.queue", text)
        self.assertIn(".activity-card-action.cancel", text)
        self.assertIn(".activity-card-action.compare", text)
        self.assertIn('.activity-card[data-status="queued"]', text)
        self.assertIn('.activity-card[data-status="cancelled"]', text)
        self.assertIn(".activity-tray-clear", text)

    def test_activity_tray_script_helpers_exist(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("const activityTrayState = {", text)
        self.assertIn("function initActivityTray() {", text)
        self.assertIn("function beginActivity({", text)
        self.assertIn("function updateActivity(activityId, patch = {}) {", text)
        self.assertIn("function completeActivity(activityId, patch = {}) {", text)
        self.assertIn("function failActivity(activityId, patch = {}) {", text)
        self.assertIn("function acceptActivity(activityId) {", text)
        self.assertIn("function clearAllActivityNotifications() {", text)
        self.assertIn("function handleActivityTrayClearAll() {", text)
        self.assertIn("function handleActivityTrayRerun(activityId) {", text)
        self.assertIn("async function handleActivityTrayCancel(activityId) {", text)
        self.assertIn("function enqueueActivityRerun(activityId) {", text)
        self.assertIn("async function launchNextQueuedActivity() {", text)
        self.assertIn("async function handleActivityTrayOpenFolder(activityId) {", text)
        self.assertIn("async function handleActivityTrayCopyCombinedPdf(activityId) {", text)
        self.assertIn("async function handleActivityTrayOpenCombinedPdf(activityId) {", text)
        self.assertIn("async function handleActivityTrayDwgCompare(activityId, pairIndex = 0) {", text)
        self.assertIn("function handleActivityTrayAccept(activityId) {", text)
        self.assertIn("function renderActivityTray() {", text)
        self.assertIn("function formatActivityDateTime(timestamp) {", text)
        self.assertIn("function formatActivityDuration(startedAt, endedAt = Date.now()) {", text)
        self.assertIn("function syncActivityTimingTimer() {", text)
        self.assertIn("function getActivityProjectName({", text)
        self.assertIn("ACTIVITY_RERUN_TOOL_IDS", text)
        self.assertIn("rerunDefaultPath", text)
        self.assertIn("rerunLaunchContext", text)
        self.assertIn("combinedPdfPath", text)
        self.assertIn('textContent: "Copy Combined PDF"', text)
        self.assertIn('textContent: "Open Combined PDF"', text)
        self.assertIn('textContent: "Rerun"', text)
        self.assertIn('textContent: "Queue Again"', text)
        self.assertIn('textContent: "Accept"', text)
        self.assertIn('"Compare Old vs New"', text)
        self.assertIn('`${isQueued ? "Queued" : "Started"}: ${formatActivityDateTime(startedAt)}`', text)
        self.assertIn('textContent: `Ended: ${formatActivityDateTime(endedAt)}`', text)
        self.assertIn('"data-activity-duration-id": item.id', text)
        self.assertIn('"data-activity-action": "copy-combined-pdf"', text)
        self.assertIn('"data-activity-action": "open-combined-pdf"', text)
        self.assertIn('"data-activity-action": "open"', text)
        self.assertIn('"data-activity-action": "rerun"', text)
        self.assertIn('"data-activity-action": "queue"', text)
        self.assertIn('"data-activity-action": "cancel"', text)
        self.assertIn('"data-activity-action": "dwg-compare"', text)
        self.assertIn('await handleActivityTrayRerun(activityId);', text)
        # Cancel buttons call the handler directly from each activity card.
        self.assertIn('void handleActivityTrayCancel(item.id);', text)
        self.assertIn("window.pywebview.api.cancel_activity(activityId)", text)
        self.assertIn('rawMessage.startsWith("INPUT_FOLDER:")', text)
        self.assertIn('rawMessage.startsWith("DWG_COMPARE_PAIR:")', text)
        self.assertIn("window.pywebview.api.launch_dwg_compare(", text)
        self.assertIn(
            'const result = await window.pywebview.api.open_path(activity.openFolderPath);',
            text,
        )
        self.assertIn(
            "window.pywebview.api.copy_file_to_clipboard(",
            text,
        )
        self.assertIn(
            "const result = await window.pywebview.api.open_path(activity.combinedPdfPath);",
            text,
        )
        self.assertIn(
            'if (result && String(result.status || "").trim().toLowerCase() !== "success") {',
            text,
        )

    def test_activity_lifecycle_tracks_start_end_and_live_duration(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("startedAt,", text)
        self.assertIn("endedAt,", text)
        self.assertIn("const endedAt = isTerminalActivityStatus(mergedStatus)", text)
        self.assertIn('isTerminal ? "Duration" : "Elapsed"', text)
        self.assertIn("() => updateActivityTimingDurations(),", text)
        self.assertIn("window.clearInterval(activityTrayState.timingTimerId);", text)

    def test_project_name_is_rendered_from_tool_launch_context(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('projectName: getActivityProjectName({', text)
        self.assertIn('launchContext: nextRerunLaunchContext', text)
        self.assertIn('className: "activity-card-project"', text)
        self.assertIn('textContent: `Project: ${projectName}`', text)

    def test_workflow_activity_title_is_rendered(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        self.assertIn("function getWorkflowDisplayName(workflow) {", text)
        self.assertIn("function getWorkflowActivityLabel(workflow) {", text)
        self.assertIn("function getActivityLabelFromPayload(toolId, payload = {}, existing = null) {", text)
        self.assertIn('normalizedToolId === "toolWorkflow" && workflowTitle', text)
        self.assertIn("const activityTitle =", text)
        self.assertIn("textContent: activityTitle", text)


if __name__ == "__main__":
    unittest.main()
