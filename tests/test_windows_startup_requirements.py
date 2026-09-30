"""The app must explain a missing WebView2 Runtime instead of opening a blank window.

Without the runtime (or .NET Framework 4.6.2) pywebview silently falls back to the old
Internet Explorer engine, which cannot run this UI. main.find_missing_windows_requirement()
looks for both up front and run() shows the answer in a message box.
"""
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import main as main_module

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
DOTNET_KEY = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"
MACHINE_KEY = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{CLIENT_GUID}"
USER_KEY = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{CLIENT_GUID}"


def fake_registry(values):
    """Stands in for _read_registry_value; keys are (hive name, subkey, value name)."""

    def read(hive_name, subkey, value_name):
        return values.get((hive_name, subkey, value_name))

    return read


def check_with(values):
    with patch.object(main_module.sys, "platform", "win32"), patch.object(
        main_module, "_read_registry_value", fake_registry(values)
    ):
        return main_module.find_missing_windows_requirement()


DOTNET_OK = {("HKEY_LOCAL_MACHINE", DOTNET_KEY, "Release"): 533320}  # .NET Framework 4.8.1


class FindMissingWindowsRequirementTests(unittest.TestCase):
    def test_machine_wide_runtime_is_accepted(self):
        values = {**DOTNET_OK, ("HKEY_LOCAL_MACHINE", MACHINE_KEY, "pv"): "139.0.3405.86"}
        self.assertIsNone(check_with(values))

    def test_per_user_runtime_is_accepted(self):
        values = {**DOTNET_OK, ("HKEY_CURRENT_USER", USER_KEY, "pv"): "139.0.3405.86"}
        self.assertIsNone(check_with(values))

    def test_a_preview_channel_counts_as_a_runtime(self):
        beta = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{main_module._WEBVIEW2_CLIENT_GUIDS[1]}"
        values = {**DOTNET_OK, ("HKEY_LOCAL_MACHINE", beta, "pv"): "140.0.1.1"}
        self.assertIsNone(check_with(values))

    def test_missing_runtime_points_to_the_webview2_download(self):
        message, url = check_with(dict(DOTNET_OK))
        self.assertIn("WebView2", message)
        self.assertEqual(main_module.WEBVIEW2_DOWNLOAD_URL, url)

    def test_placeholder_and_too_old_versions_do_not_count(self):
        for build in ("0.0.0.0", "", "85.0.564.68", "not a version"):
            with self.subTest(build=build):
                values = {**DOTNET_OK, ("HKEY_LOCAL_MACHINE", MACHINE_KEY, "pv"): build}
                message, _url = check_with(values)
                self.assertIn("WebView2", message)

    def test_old_dotnet_framework_is_reported_first(self):
        values = {
            ("HKEY_LOCAL_MACHINE", DOTNET_KEY, "Release"): 394254,  # 4.6.1
            ("HKEY_LOCAL_MACHINE", MACHINE_KEY, "pv"): "139.0.3405.86",
        }
        message, url = check_with(values)
        self.assertIn(".NET Framework", message)
        self.assertEqual(main_module.DOTNET_FRAMEWORK_DOWNLOAD_URL, url)

    def test_no_dotnet_framework_at_all_is_reported(self):
        message, _url = check_with({("HKEY_LOCAL_MACHINE", MACHINE_KEY, "pv"): "139.0.3405.86"})
        self.assertIn(".NET Framework", message)

    def test_other_platforms_are_not_checked(self):
        with patch.object(main_module.sys, "platform", "linux"):
            self.assertIsNone(main_module.find_missing_windows_requirement())


class ShowStartupProblemTests(unittest.TestCase):
    def _run(self, answer, url, environment):
        message_box = MagicMock(return_value=answer)
        windll = MagicMock()
        windll.user32.MessageBoxW = message_box
        startfile = MagicMock()
        with patch.object(main_module.sys, "platform", "win32"), patch.dict(
            os.environ, environment, clear=False
        ), patch("ctypes.windll", windll, create=True), patch.object(
            main_module.os, "startfile", startfile, create=True
        ):
            main_module._show_startup_problem("Something is missing.", url)
        return message_box, startfile

    def _interactive(self):
        return {"ACIES_NONINTERACTIVE": ""}

    def test_yes_opens_the_download_page(self):
        message_box, startfile = self._run(6, main_module.WEBVIEW2_DOWNLOAD_URL, self._interactive())
        message_box.assert_called_once()
        startfile.assert_called_once_with(main_module.WEBVIEW2_DOWNLOAD_URL)

    def test_no_leaves_the_browser_alone(self):
        _message_box, startfile = self._run(7, main_module.WEBVIEW2_DOWNLOAD_URL, self._interactive())
        startfile.assert_not_called()

    def test_a_problem_without_a_download_is_just_shown(self):
        message_box, startfile = self._run(1, None, self._interactive())
        message_box.assert_called_once()
        startfile.assert_not_called()

    def test_automated_runs_never_open_a_dialog(self):
        message_box, startfile = self._run(6, main_module.WEBVIEW2_DOWNLOAD_URL, {"ACIES_NONINTERACTIVE": "1"})
        message_box.assert_not_called()
        startfile.assert_not_called()


class InstallerAndRunWiringTests(unittest.TestCase):
    def test_run_checks_requirements_before_opening_the_window(self):
        text = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        run_body = text.split("def run():", 1)[1]
        self.assertLess(
            run_body.index("find_missing_windows_requirement()"),
            run_body.index("webview.create_window("),
        )
        self.assertIn("_export_pdf_helper_python()", run_body)

    def test_installer_refuses_unsupported_windows_and_installs_the_runtime(self):
        text = (REPO_ROOT / "build-config" / "setup.iss").read_text(encoding="utf-8")
        self.assertIn("MinVersion=10.0.14393", text)
        self.assertIn("MicrosoftEdgeWebview2Setup.exe", text)
        self.assertIn("/silent /install", text)
        self.assertIn("F3017226-FE2A-4295-8BDF-00C3A9A7E4C5", text)

    def test_build_fetches_a_signed_bootstrapper_and_checks_the_pdf_helper(self):
        text = (REPO_ROOT / "build-config" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("Ensure-WebView2Bootstrapper", text)
        self.assertIn("Get-AuthenticodeSignature", text)
        self.assertIn('"acies-pdf-tools.exe"', text)

    def test_both_specs_ship_the_pdf_helper_and_discovery_script(self):
        for spec in ("ACIES Scheduler.spec", "build-config/ACIES Scheduler.spec"):
            with self.subTest(spec=spec):
                text = (REPO_ROOT / spec).read_text(encoding="utf-8")
                self.assertIn("pdf_helper_runner.py", text)
                self.assertIn("name='acies-pdf-tools'", text)
                self.assertIn("console=True", text)
                self.assertIn("AutoCadDiscovery.ps1", text)


if __name__ == "__main__":
    unittest.main()
