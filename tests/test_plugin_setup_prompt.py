"""Backend pieces of the first-run AutoCAD plugin prompt.

The prompt itself is in script.js (tests/plugin_setup_prompt.test.cjs). The backend
supplies its saved choice and the signal it needs to stop when AutoCAD is open.
"""
import tempfile
import unittest
from unittest.mock import patch

import main as main_module
from main import Api


class PluginSetupPromptBackendTests(unittest.TestCase):
    def test_the_prompt_is_on_by_default(self):
        self.assertIs(True, main_module.build_default_user_settings()["showPluginSetupPrompt"])

    def test_a_saved_choice_not_to_be_asked_survives_sanitizing(self):
        saved = {"showPluginSetupPrompt": False}

        sanitized, _changed = main_module._sanitize_user_settings_payload(saved)

        self.assertIs(False, sanitized["showPluginSetupPrompt"])

    def test_settings_saved_before_the_prompt_existed_get_the_default(self):
        sanitized, changed = main_module._sanitize_user_settings_payload({"userName": "Old Settings"})

        self.assertTrue(changed)
        self.assertIs(True, sanitized["showPluginSetupPrompt"])

    def test_installing_while_autocad_runs_returns_a_code_the_prompt_can_stop_on(self):
        api = Api.__new__(Api)
        api.release_tag = "v0.2.1"
        with tempfile.TemporaryDirectory(prefix="acies-plugin-prompt-") as plugins_dir:
            api.app_plugins_folder = plugins_dir
            with patch.object(api, "_is_autocad_running", return_value=True), patch.object(
                main_module.requests, "get"
            ) as get:
                result = api.install_single_bundle(
                    {"name": "ElectricalCommands.CleanCADCommands-v0.2.1.zip",
                     "browser_download_url": "https://example.com/clean.zip"}
                )

        self.assertEqual("error", result["status"])
        self.assertEqual("autocad_running", result["code"])
        self.assertIn("AutoCAD is currently running", result["message"])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
