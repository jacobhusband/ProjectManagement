"""AutoCAD is found from Autodesk's registry entries and Program Files, on any drive.

The app's picker (main.discover_autocad_installs) and the PowerShell scripts'
fallback (scripts/AutoCadDiscovery.ps1) must agree, and neither may hard-code a
list of release years.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as main_module

REPO_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_SCRIPT = REPO_ROOT / "scripts" / "AutoCadDiscovery.ps1"
CAD_SCRIPTS = (
    "PlotDWGs.ps1",
    "ManageLayersDWGs.ps1",
    "ManageXrefPathsDWGs.ps1",
    "removeXREFPaths.ps1",
)


def make_install(parent, folder_name, with_console=True):
    folder = Path(parent) / folder_name
    folder.mkdir(parents=True)
    if with_console:
        (folder / "accoreconsole.exe").write_bytes(b"")
    return folder


class DiscoverAutocadInstallsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acies-acad-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def discover(self, registry=(), program_files=()):
        with patch.object(main_module, "_autocad_registry_installs", lambda: iter(registry)), patch.object(
            main_module, "_autocad_program_files_installs", lambda: iter(program_files)
        ):
            return main_module.discover_autocad_installs()

    def test_finds_a_release_that_was_never_hard_coded_on_another_drive(self):
        other_drive = make_install(self.root / "D_drive" / "CAD", "AutoCAD 2027")

        found = self.discover(registry=[(str(other_drive), "AutoCAD 2027 - English")])

        self.assertEqual([2027], [item["year"] for item in found])
        self.assertEqual(str(other_drive / "accoreconsole.exe"), found[0]["path"])

    def test_lists_newest_first_and_merges_registry_and_folder_hits(self):
        program_files = self.root / "Program Files" / "Autodesk"
        for year in (2022, 2025, 2024):
            make_install(program_files, f"AutoCAD {year}")
        registry = [(str(program_files / f"AutoCAD {year}") + "\\", f"AutoCAD {year} - English") for year in (2022, 2025)]
        folders = [(str(program_files / f"AutoCAD {year}"), f"AutoCAD {year}") for year in (2022, 2025, 2024)]

        found = self.discover(registry=registry, program_files=folders)

        self.assertEqual([2025, 2024, 2022], [item["year"] for item in found])

    def test_skips_releases_older_than_the_scripts_support(self):
        old = make_install(self.root, "AutoCAD 2019")
        supported = make_install(self.root, "AutoCAD 2020")

        found = self.discover(registry=[(str(old), "AutoCAD 2019"), (str(supported), "AutoCAD 2020")])

        self.assertEqual([2020], [item["year"] for item in found])

    def test_skips_installs_without_a_core_console(self):
        lt = make_install(self.root, "AutoCAD LT 2025", with_console=False)

        self.assertEqual([], self.discover(registry=[(str(lt), "AutoCAD LT 2025")]))

    def test_reads_the_year_from_the_product_name_when_the_folder_was_renamed(self):
        renamed = make_install(self.root, "CAD")

        found = self.discover(registry=[(str(renamed), "AutoCAD 2026 - English")])

        self.assertEqual([2026], [item["year"] for item in found])

    def test_an_install_with_no_readable_year_is_kept_but_listed_last(self):
        known = make_install(self.root, "AutoCAD 2024")
        unknown = make_install(self.root, "CAD")

        found = self.discover(registry=[(str(unknown), ""), (str(known), "AutoCAD 2024")])

        self.assertEqual([2024, 0], [item["year"] for item in found])

    def test_api_returns_the_discovered_installs(self):
        api = main_module.Api.__new__(main_module.Api)
        with patch.object(main_module, "discover_autocad_installs", return_value=[{"year": 2026, "path": "x"}]):
            self.assertEqual(
                {"status": "success", "versions": [{"year": 2026, "path": "x"}]},
                api.get_installed_autocad_versions(),
            )

    def test_api_reports_a_failed_scan_instead_of_raising(self):
        api = main_module.Api.__new__(main_module.Api)
        with patch.object(main_module, "discover_autocad_installs", side_effect=OSError("boom")):
            result = api.get_installed_autocad_versions()
        self.assertEqual("error", result["status"])
        self.assertEqual([], result["versions"])

    def test_program_files_scan_only_lists_autocad_release_folders(self):
        autodesk = self.root / "Autodesk"
        make_install(autodesk, "AutoCAD 2026")
        make_install(autodesk, "AutoCAD Activity Insights")
        make_install(autodesk, "Revit 2025")
        with patch.dict(main_module.os.environ, {"ProgramW6432": str(self.root), "ProgramFiles": ""}):
            found = [name for _folder, name in main_module._autocad_program_files_installs()]
        self.assertEqual(["AutoCAD 2026"], found)


@unittest.skipUnless(sys.platform == "win32", "The CAD scripts run in Windows PowerShell")
class PowerShellDiscoveryTests(unittest.TestCase):
    def find(self, program_files_root):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        self.assertIsNotNone(powershell)
        command = (
            f". '{DISCOVERY_SCRIPT}'; "
            f"$r = @(Find-AcadCoreConsole -SkipRegistry -ProgramFilesRoots @('{program_files_root}')); "
            "ConvertTo-Json -InputObject $r -Compress"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_matches_the_python_scan(self):
        with tempfile.TemporaryDirectory(prefix="acies-acad-ps-") as temp_dir:
            autodesk = Path(temp_dir) / "Autodesk"
            make_install(autodesk, "AutoCAD 2025")
            make_install(autodesk, "AutoCAD 2027")
            make_install(autodesk, "AutoCAD 2019")
            make_install(autodesk, "AutoCAD 2026", with_console=False)
            make_install(autodesk, "AutoCAD Activity Insights")

            found = self.find(temp_dir)

            self.assertEqual([2027, 2025], [item["Year"] for item in found])
            # Compare resolved paths: the GitHub runner's temp folder is a short 8.3 name
            # (C:\Users\RUNNER~1\...) that PowerShell reports in its long form.
            self.assertEqual(
                (autodesk / "AutoCAD 2027" / "accoreconsole.exe").resolve(),
                Path(found[0]["Path"]).resolve(),
            )

    def test_finds_nothing_when_autocad_is_absent(self):
        with tempfile.TemporaryDirectory(prefix="acies-acad-ps-") as temp_dir:
            self.assertEqual([], self.find(temp_dir))


class CadScriptsUseSharedDiscoveryTests(unittest.TestCase):
    def test_each_script_falls_back_to_the_shared_finder(self):
        for name in CAD_SCRIPTS:
            with self.subTest(script=name):
                text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
                self.assertIn("AutoCadDiscovery.ps1", text)
                self.assertIn("Find-AcadCoreConsole", text)
                # The old fixed year lists stopped at the newest release someone remembered to add.
                self.assertNotIn(r"C:\Program Files\Autodesk\AutoCAD $year", text)


if __name__ == "__main__":
    unittest.main()
