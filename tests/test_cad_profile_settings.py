"""CAD scripts must leave the user's own AutoCAD settings as they found them.

Core Console runs without /isolate, so it reads and saves the same AutoCAD profile as
the user's AutoCAD. A script that sets a profile-backed variable (SECURELOAD, CMDDIA,
FILEDIA, PROXYNOTICE, BACKGROUNDPLOT, ...) and never sets it back changes the user's
AutoCAD. A new user reported their settings changing after trying the app.
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
CAD_SCRIPTS = (
    "PlotDWGs.ps1",
    "ManageLayersDWGs.ps1",
    "ManageXrefPathsDWGs.ps1",
    "removeXREFPaths.ps1",
    "ListDwgXrefs.ps1",
)
# Variables Core Console scripts used to set without restoring.
UNRESTORED_DIALOG_SETTINGS = ("CMDDIA", "FILEDIA", "PROXYNOTICE", "DYNMODE")


class CadProfileSettingsTests(unittest.TestCase):
    def test_scripts_do_not_change_dialog_settings(self):
        for name in CAD_SCRIPTS:
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            for variable in UNRESTORED_DIALOG_SETTINGS:
                # A command-line ("CMDDIA 0" / "CMDDIA","0") or (setvar "CMDDIA" ...) write.
                pattern = rf'"{variable}"\s*,\s*"[01]"|"{variable}"\s*,\s*\r?\n\s*"[01]"|\b{variable} [01]\b|\(setvar "{variable}"'
                self.assertIsNone(re.search(pattern, text), f"{name} sets {variable}")

    def test_secureload_is_only_lowered_through_the_restoring_helper(self):
        for name in CAD_SCRIPTS:
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r'SECURELOAD\s+0|"SECURELOAD"\s*,\s*"0"|"SECURELOAD",\s*\r?\n\s*"0"',
                                f"{name} lowers SECURELOAD without restoring it")

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell is required")
    def test_trusted_load_lines_restore_secureload_right_after_loading(self):
        command = (
            f". '{SCRIPTS / 'AutoCadDiscovery.ps1'}'; "
            "Get-AcadTrustedLoadScriptLines -LoadLines @('_.NETLOAD', '\"C:/tool.dll\"')"
        )
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([
            '(setq aciesSavedSecureLoad (getvar "SECURELOAD"))',
            '(setvar "SECURELOAD" 0)',
            '_.NETLOAD',
            '"C:/tool.dll"',
            '(setvar "SECURELOAD" aciesSavedSecureLoad)',
        ], result.stdout.splitlines())

    def test_plot_restores_publish_settings_before_every_quit_after_preflight(self):
        text = (SCRIPTS / "PlotDWGs.ps1").read_text(encoding="utf-8")
        start = text.index("(defun PlotLayoutsAfterPreflight")
        body = text[start:text.index("(defun c:PlotAllLayouts", start)]
        quits = body.count('(command "_.QUIT")')
        self.assertGreater(quits, 0)
        self.assertEqual(quits, len(re.findall(r'\(AciesRestorePlotSettings\)\s*\(command "_\.QUIT"\)', body)))
        self.assertIn("(AciesRestorePlotSettings)", body[:body.index("(setq preflightResult")])  # *error* path
        preflight = text[text.index("(defun EnsurePublishPreflight"):]
        self.assertLess(preflight.index("(AciesSavePlotSettings)"), preflight.index('(setvar "BACKGROUNDPLOT" 0)'))


if __name__ == "__main__":
    unittest.main()
