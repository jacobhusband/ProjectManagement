"""Publish DWGs checks that AutoCAD has its plot style table before it starts.

510-monochrome.ctb is not part of an AutoCAD install, so a PC that never received it
cannot plot. The check reads the plot style folders AutoCAD itself uses and stops with
a message that says where the file belongs. It must never stop a job on a guess: an
AutoCAD it cannot identify is let through.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as main_module
from main import Api

STYLE = main_module.PUBLISH_PLOT_STYLE_NAME


class PlotStyleTableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acies-ctb-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.appdata = self.root / "AppData" / "Roaming"
        self.appdata.mkdir(parents=True)
        self.install = self.root / "Autodesk" / "AutoCAD 2025"
        self.install.mkdir(parents=True)
        self.acad = self.install / "accoreconsole.exe"
        self.acad.write_bytes(b"")
        env = patch.dict(os.environ, {"APPDATA": str(self.appdata)})
        env.start()
        self.addCleanup(env.stop)

    def plot_styles_folder(self, year="2025", release="R25.0", language="enu"):
        folder = self.appdata / "Autodesk" / f"AutoCAD {year}" / release / language / "Plotters" / "Plot Styles"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def find(self, entries=None, profile_dirs=()):
        if entries is None:
            entries = [("R25.0", "ACAD-8101:409", str(self.install) + "\\", "AutoCAD 2025 - English")]
        with patch.object(main_module, "_autocad_registry_entries", lambda: iter(entries)), patch.object(
            main_module, "_plot_style_dirs_from_profiles", lambda release, product: iter(profile_dirs)
        ):
            return main_module.find_plot_style_table(str(self.acad))

    def test_found_in_the_default_plot_style_folder(self):
        (self.plot_styles_folder() / STYLE).write_bytes(b"ctb")

        result = self.find()

        self.assertEqual("found", result["status"])
        self.assertEqual(str(self.plot_styles_folder() / STYLE), result["path"])

    def test_missing_reports_where_it_looked_and_the_release(self):
        folder = self.plot_styles_folder()

        result = self.find()

        self.assertEqual("missing", result["status"])
        self.assertEqual("2025", result["year"])
        self.assertEqual([str(folder)], result["searched"])

    def test_another_releases_copy_does_not_count(self):
        # AutoCAD 2025 never sees a file that only exists in AutoCAD 2022's profile.
        (self.plot_styles_folder(year="2022", release="R24.1") / STYLE).write_bytes(b"ctb")
        self.plot_styles_folder()

        self.assertEqual("missing", self.find()["status"])

    def test_a_profile_pointing_at_a_shared_folder_counts(self):
        shared = self.root / "CAD standards" / "Plot Styles"
        shared.mkdir(parents=True)
        (shared / STYLE).write_bytes(b"ctb")
        self.plot_styles_folder()

        result = self.find(profile_dirs=[f"{shared};%RoamableRootFolder%Plotters\\Plot Styles"])

        self.assertEqual("found", result["status"])
        self.assertEqual(str(shared / STYLE), result["path"])

    def test_a_shared_folder_counts_even_when_no_roaming_folder_exists_yet(self):
        # A profile lists "<shared folder>;%RoamableRootFolder%Plotters\Plot Styles". With
        # no roaming folder the token cannot be expanded, which must not discard the
        # shared folder next to it.
        shared = self.root / "CAD standards" / "Plot Styles"
        shared.mkdir(parents=True)
        (shared / STYLE).write_bytes(b"ctb")

        result = self.find(profile_dirs=[f"{shared};%RoamableRootFolder%Plotters\\Plot Styles"])

        self.assertEqual("found", result["status"])
        self.assertEqual(str(shared / STYLE), result["path"])

    def test_the_roaming_folder_token_in_a_profile_is_expanded_for_this_release(self):
        folder = self.plot_styles_folder()
        (folder / STYLE).write_bytes(b"ctb")

        result = self.find(profile_dirs=["%RoamableRootFolder%Plotters\\Plot Styles"])

        self.assertEqual("found", result["status"])

    def test_an_autocad_that_is_not_registered_is_let_through(self):
        self.assertEqual("unknown", self.find(entries=[])["status"])

    def test_an_install_whose_release_cannot_be_read_is_let_through(self):
        odd = self.root / "CAD" / "Acad"
        odd.mkdir(parents=True)
        (odd / "accoreconsole.exe").write_bytes(b"")
        entries = [("R25.0", "ACAD-8101:409", str(odd), "AutoCAD")]
        with patch.object(main_module, "_autocad_registry_entries", lambda: iter(entries)):
            result = main_module.find_plot_style_table(str(odd / "accoreconsole.exe"))

        self.assertEqual("unknown", result["status"])


class PublishPreflightTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.api.test_mode = False
        self.settings = {"autocadPath": r"C:\Autodesk\AutoCAD 2025\accoreconsole.exe"}

    def run_publish(self, finder_result):
        with patch.object(self.api, "get_user_settings", return_value=self.settings), patch.object(
            main_module, "find_plot_style_table", return_value=finder_result
        ), patch.object(self.api, "_run_script_with_progress") as run_mock, patch.object(
            self.api, "_select_cad_files_in_app"
        ) as picker_mock, patch.object(self.api, "_notify_tool_status") as notify_mock:
            result = self.api.run_publish_script({"source": "projects-tab"}, activity_id="act-1")
        return result, run_mock, picker_mock, notify_mock

    def test_missing_style_stops_before_any_file_is_picked_or_plotted(self):
        folder = r"C:\Users\New\AppData\Roaming\Autodesk\AutoCAD 2025\R25.0\enu\Plotters\Plot Styles"
        result, run_mock, picker_mock, notify_mock = self.run_publish(
            {"status": "missing", "searched": [folder], "year": "2025"}
        )

        self.assertEqual("error", result["status"])
        self.assertEqual("act-1", result["activityId"])
        self.assertIn(STYLE, result["message"])
        self.assertIn("AutoCAD 2025", result["message"])
        self.assertIn(folder, result["message"])
        run_mock.assert_not_called()
        picker_mock.assert_not_called()
        notify_mock.assert_called_once_with(
            "toolPublishDwgs", f"ERROR: {result['message']}", activity_id="act-1"
        )

    def test_a_found_or_unknown_style_does_not_stop_the_publish(self):
        for finder_result in ({"status": "found", "path": "x"}, {"status": "unknown"}):
            with self.subTest(finder_result["status"]), patch.object(
                main_module, "find_plot_style_table", return_value=finder_result
            ):
                self.assertEqual("", self.api._plot_style_problem(self.settings["autocadPath"]))

    def test_a_fault_in_the_check_never_stops_a_publish(self):
        with patch.object(main_module, "find_plot_style_table", side_effect=OSError("registry unreadable")):
            self.assertEqual("", self.api._plot_style_problem(self.settings["autocadPath"]))


if __name__ == "__main__":
    unittest.main()
