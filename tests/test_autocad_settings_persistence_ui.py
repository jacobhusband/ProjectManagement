import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_JS_PATH = REPO_ROOT / "script.js"


class AutocadSettingsPersistenceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT_JS_PATH.read_text(encoding="utf-8")

    def _block(self, start_marker, end_marker):
        start = self.script.index(start_marker)
        end = self.script.index(end_marker, start)
        return self.script[start:end]

    def test_save_user_settings_preserves_unpopulated_autocad_path(self):
        save_block = self._block(
            "async function saveUserSettings() {",
            "const debouncedSaveUserSettings = debounce(saveUserSettings, 500);",
        )

        self.assertIn("let settingsAutocadControlsPopulated = false;", self.script)
        self.assertIn("let settingsAutocadPathExplicitlyChanged = false;", self.script)
        self.assertIn(
            "if (settingsAutocadControlsPopulated || settingsAutocadPathExplicitlyChanged)",
            save_block,
        )
        self.assertIn(
            'document.querySelector(\n      \'input[name="autocad_version_radio"]:checked\'',
            save_block,
        )
        self.assertIn(
            'const settingsAutocadInput = document.getElementById("settings_autocadPath");',
            save_block,
        )
        self.assertIn(
            'userSettings.autocadPath = String(settingsAutocadInput?.value || "").trim();',
            save_block,
        )
        self.assertNotIn("// Update autocadPath from UI", save_block)

    def test_cad_tool_launches_refresh_persisted_autocad_path_before_prompting(self):
        self.assertIn("async function ensureAutocadPathLoaded() {", self.script)
        self.assertIn(
            "const storedSettings = await window.pywebview.api.get_user_settings();",
            self.script,
        )
        self.assertIn(
            "userSettings.autocadPath = storedPath;",
            self.script,
        )

        for tool_id in ("toolPublishDwgs", "toolManageLayers", "toolCleanXrefs"):
            block = self._block(
                f'.getElementById("{tool_id}")',
                "const activityId = beginActivity({",
            )
            self.assertIn("if (!(await ensureAutocadPathLoaded())) {", block)
            self.assertIn("await showAutocadSelectModal();", block)


if __name__ == "__main__":
    unittest.main()
