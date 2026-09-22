import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import main as main_module


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = REPO_ROOT / "main.py"
SCRIPT_PATH = REPO_ROOT / "script.js"
INDEX_PATH = REPO_ROOT / "index.html"
SPEC_PATH = REPO_ROOT / "ACIES Scheduler.spec"
POWERSHELL_PATH = REPO_ROOT / "scripts" / "ManageXrefPathsDWGs.ps1"


class RepairXrefPathsToolTests(unittest.TestCase):
    def test_backend_passes_selected_dwgs_to_packaged_script(self):
        api = main_module.Api.__new__(main_module.Api)
        api.test_mode = False
        dwg_path = r"C:\Projects\260001 Example\Electrical\E02.00 Lighting.dwg"
        files_list_path = r"C:\Temp\selected-repair-xref-dwgs.txt"
        captured = []
        with patch.object(
            api,
            "get_user_settings",
            return_value={"autocadPath": r"C:\AutoCAD\accoreconsole.exe"},
        ), patch.object(
            api, "_get_launch_context_cad_file_paths", return_value=[dwg_path]
        ), patch.object(
            api, "_write_files_list_temp", return_value=files_list_path
        ) as write_list_mock, patch.object(
            api,
            "_run_script_with_progress",
            side_effect=lambda command, tool_id, **kwargs: captured.append(
                (command, tool_id, kwargs)
            )
            or {"status": "started"},
        ), patch.object(api, "_trace_cad_auto_select"), patch.object(
            api, "_notify_tool_status"
        ) as notify_mock:
            result = api.run_repair_xref_paths_script(
                {"source": "manual", "cadFilePaths": [dwg_path]},
                "repair-activity",
            )

        self.assertEqual("success", result["status"])
        self.assertEqual(1, len(captured))
        command, tool_id, kwargs = captured[0]
        self.assertEqual("toolRepairXrefPaths", tool_id)
        self.assertEqual({"activity_id": "repair-activity"}, kwargs)
        self.assertTrue(command[command.index("-File") + 1].endswith("ManageXrefPathsDWGs.ps1"))
        self.assertIn("-FilesListPath", command)
        self.assertEqual(
            files_list_path, command[command.index("-FilesListPath") + 1]
        )
        write_list_mock.assert_called_once_with([dwg_path])
        notify_mock.assert_called_once_with(
            "toolRepairXrefPaths",
            "Using selected DWGs (1)...",
            activity_id="repair-activity",
        )

    def test_tool_is_registered_in_backend_frontend_and_build(self):
        main_text = MAIN_PATH.read_text(encoding="utf-8")
        script_text = SCRIPT_PATH.read_text(encoding="utf-8")
        index_text = INDEX_PATH.read_text(encoding="utf-8")
        spec_text = SPEC_PATH.read_text(encoding="utf-8")

        for expected in (
            "'repairXrefPaths': {",
            "def run_repair_xref_paths_script(",
            '"ManageXrefPathsDWGs.ps1"',
            "'toolRepairXrefPaths'",
        ):
            self.assertIn(expected, main_text)

        for expected in (
            'id: "toolRepairXrefPaths"',
            'label: "Repair XREF Paths"',
            'launchType: "user-selects-files"',
            '.getElementById("toolRepairXrefPaths")',
            "run_repair_xref_paths_script(",
            '"toolRepairXrefPaths",',
        ):
            self.assertIn(expected, script_text)

        self.assertIn('id="toolRepairXrefPaths"', index_text)
        self.assertIn("Repair XREF Paths", index_text)
        self.assertIn(r"scripts\\ManageXrefPathsDWGs.ps1", spec_text)

    def test_script_scans_deduplicates_disables_dependencies_and_verifies_saves(self):
        text = POWERSHELL_PATH.read_text(encoding="utf-8")

        for expected in (
            "ACIESXREFSCAN",
            "_acies-parent-xref-available",
            "Get-XrefIdentityKey",
            "$groupMap",
            '"Not Found"',
            '"Found"',
            '"Orphaned"',
            "Editable = (-not $dependent)",
            '"Nested/orphaned - edit parent DWG"',
            "ACIESXREFUPDATE",
            "(entmod changedRecord)",
            '"ALREADY_SET"',
            '"UPDATED"',
            '"SAVE_OK"',
            "$updatesOkay",
            "$saveOkay",
        ):
            self.assertIn(expected, text)

        self.assertNotIn('Filter = "All files (*.*)|*.*"', text)
        self.assertNotIn("vlax-get-acad-object", text)
        self.assertIn('"_.QUIT", "_N"', text)
        self.assertNotIn("$items = @($_.Occurrences)", text)
        self.assertIn(
            "$items = @($_.Occurrences | ForEach-Object { $_ })",
            text,
        )

    def test_script_avoids_ambiguous_split_path_parameter_set(self):
        text = POWERSHELL_PATH.read_text(encoding="utf-8")

        self.assertNotRegex(text, r"Split-Path\s+-LiteralPath[^\r\n]*-Parent")
        self.assertIn("function Get-ParentDirectory", text)
        self.assertIn(
            'Write-Host "PROGRESS: ERROR: XREF path repair failed: $message"',
            text,
        )
        self.assertNotIn("param([int]$Pid)", text)
        self.assertIn("Stop-ProcessTree -ProcessId $process.Id", text)

    def test_powershell_script_parses(self):
        command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{POWERSHELL_PATH}', [ref]$tokens, [ref]$errors) | Out-Null; "
            "$errors | ForEach-Object { Write-Error $_.ToString() }; "
            "if ($errors.Count -gt 0) { exit 1 }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
