"""The combined AutoCAD plugin bundle and its command switches.

Plugin releases after v0.3.0 ship one ElectricalCommands.bundle. Installing it removes
the per-plugin bundles it replaces, and its commands.json lists the commands a user
may switch off; the choice is saved as a plain list the plugin reads in AutoCAD.
"""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import main as main_module
from main import Api

COMBINED = "ElectricalCommands.bundle"
LEGACY_CLEAN = "ElectricalCommands.CleanCADCommands.bundle"


def combined_release(tag="v0.4.0"):
    return {
        "tag": tag,
        "assets": [{"name": f"ElectricalCommands-{tag}.zip",
                    "browser_download_url": "https://example.com/all.zip"}],
        "release_notes": "",
        "html_url": "",
    }


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class CombinedPluginBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acies-combined-plugin-")
        self.addCleanup(self.temp.cleanup)
        self.plugins = Path(self.temp.name) / "ApplicationPlugins"
        self.plugins.mkdir()
        self.api = Api.__new__(Api)
        self.api.app_plugins_folder = str(self.plugins)
        self.api.plugin_settings_folder = str(Path(self.temp.name) / "settings")
        self.api.release_tag = None
        self.api._is_autocad_running = lambda: False

    def statuses(self, release):
        with patch.object(self.api, "_fetch_latest_bundle_release", return_value=release):
            result = self.api.get_bundle_statuses()
        self.assertEqual("success", result["status"])
        return {item["bundle_name"]: item for item in result["data"]}

    def install(self, files):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle_zip:
            for name, text in files.items():
                bundle_zip.writestr(name, text)
        self.api.release_tag = "v0.4.0"
        with patch("main.requests.get", return_value=FakeResponse(archive.getvalue())):
            return self.api.install_single_bundle(combined_release()["assets"][0])

    def write_catalog(self, modules):
        bundle = self.plugins / COMBINED
        bundle.mkdir(exist_ok=True)
        (bundle / "commands.json").write_text(
            json.dumps({"version": "0.4.0", "modules": modules}), encoding="utf-8")

    def test_a_combined_release_is_listed_as_one_plugin(self):
        statuses = self.statuses(combined_release())

        self.assertEqual([COMBINED], list(statuses))
        self.assertEqual("not_installed", statuses[COMBINED]["state"])

    def test_older_per_plugin_bundles_show_as_an_update_to_the_combined_one(self):
        legacy = self.plugins / LEGACY_CLEAN
        legacy.mkdir()
        (legacy / "version.txt").write_text("v0.3.0")

        statuses = self.statuses(combined_release())

        self.assertEqual([COMBINED], list(statuses))
        self.assertEqual("update_available", statuses[COMBINED]["state"])
        self.assertEqual("v0.3.0", statuses[COMBINED]["local_version"])

    def test_another_vendors_bundle_is_still_listed_beside_the_combined_one(self):
        (self.plugins / "Vendor.Tools.bundle").mkdir()

        statuses = self.statuses(combined_release())

        self.assertEqual({COMBINED, "Vendor.Tools.bundle"}, set(statuses))

    def test_installing_the_combined_bundle_removes_the_bundles_it_replaces(self):
        (self.plugins / LEGACY_CLEAN).mkdir()
        (self.plugins / "Vendor.Tools.bundle").mkdir()

        result = self.install({"PackageContents.xml": "<ApplicationPackage />"})

        self.assertEqual("success", result["status"])
        self.assertEqual([LEGACY_CLEAN], result["removedLegacyBundles"])
        self.assertTrue((self.plugins / COMBINED / "PackageContents.xml").exists())
        self.assertFalse((self.plugins / LEGACY_CLEAN).exists())
        self.assertTrue((self.plugins / "Vendor.Tools.bundle").exists())

    def test_command_list_is_empty_until_the_combined_bundle_is_installed(self):
        result = self.api.get_plugin_command_settings()

        self.assertEqual("success", result["status"])
        self.assertFalse(result["installed"])

    def test_switched_off_commands_are_saved_as_one_name_per_line(self):
        self.write_catalog([{"id": "TextCommands", "title": "Text", "commands": [
            {"name": "TA", "description": "Adds a value."}, {"name": "TN"}]}])

        saved = self.api.save_plugin_command_settings(["tn", "TA", "tn", "not a command!"])
        loaded = self.api.get_plugin_command_settings()

        self.assertEqual(["TA", "TN"], saved["disabled"])
        self.assertEqual(["TA", "TN"], loaded["disabled"])
        self.assertEqual(["TA", "TN"], [c["name"] for c in loaded["modules"][0]["commands"]])
        lines = Path(self.api._plugin_command_settings_path()).read_text(encoding="utf-8").splitlines()
        self.assertEqual(["TA", "TN"], [line for line in lines if not line.startswith("#")])

    def test_turning_every_command_back_on_empties_the_list(self):
        self.write_catalog([{"id": "TextCommands", "commands": [{"name": "TA"}]}])
        self.api.save_plugin_command_settings(["TA"])

        self.api.save_plugin_command_settings([])

        self.assertEqual([], self.api.get_plugin_command_settings()["disabled"])

    def test_the_choice_survives_a_plugin_update(self):
        self.write_catalog([{"id": "TextCommands", "commands": [{"name": "TA"}]}])
        self.api.save_plugin_command_settings(["TA"])

        self.install({
            "PackageContents.xml": "<ApplicationPackage />",
            "commands.json": json.dumps({"modules": [
                {"id": "TextCommands", "commands": [{"name": "TA"}, {"name": "TZ"}]}]}),
        })

        self.assertEqual(["TA"], self.api.get_plugin_command_settings()["disabled"])

    def test_stale_disabled_names_are_not_returned_after_commands_are_removed(self):
        self.write_catalog([{"id": "TextCommands", "commands": [{"name": "TEXTADD"}]}])
        path = Path(self.api._plugin_command_settings_path())
        path.parent.mkdir(parents=True)
        path.write_text("TA\nCLEANCAD2\nTEXTADD\n", encoding="utf-8")

        self.assertEqual(["TEXTADD"], self.api.get_plugin_command_settings()["disabled"])
        saved = self.api.save_plugin_command_settings(["TA", "CLEANCAD2", "TEXTADD"])
        self.assertEqual(["TEXTADD"], saved["disabled"])
        self.assertNotIn("CLEANCAD2", path.read_text())

    def test_automation_commands_cannot_be_switched_off_even_in_an_older_catalog(self):
        self.write_catalog([{"id": "CleanCADCommands", "commands": [
            {"name": "CLEANCAD2"}, {"name": "CLEANREVIEW"}]}])
        catalog_path = self.plugins / COMBINED / "commands.json"
        catalog = json.loads(catalog_path.read_text())
        catalog["alwaysOn"] = ["cleancad2"]
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

        loaded = self.api.get_plugin_command_settings()
        self.assertEqual(["CLEANREVIEW"], [c["name"] for c in loaded["modules"][0]["commands"]])
        saved = self.api.save_plugin_command_settings(["CLEANCAD2", "CLEANREVIEW"])
        self.assertEqual(["CLEANREVIEW"], saved["disabled"])

    def test_saving_without_a_catalog_preserves_existing_settings(self):
        path = Path(self.api._plugin_command_settings_path())
        path.parent.mkdir(parents=True)
        path.write_text("TEXTADD\n", encoding="utf-8")

        self.assertEqual("error", self.api.save_plugin_command_settings([])["status"])
        self.assertEqual("TEXTADD\n", path.read_text())


class CleanDrawingsPluginPathTests(unittest.TestCase):
    def test_clean_drawings_finds_its_plugin_in_the_combined_bundle(self):
        import clean_drawings

        with tempfile.TemporaryDirectory(prefix="acies-clean-plugin-") as temp_dir:
            acad = Path(temp_dir) / "AutoCAD 2025" / "accoreconsole.exe"
            acad.parent.mkdir()
            acad.write_bytes(b"")
            dll = (Path(temp_dir) / "Autodesk" / "ApplicationPlugins" / COMBINED / "Contents"
                   / "net8.0-windows" / "AutoCADCommands.CleanCADCommands.dll")
            dll.parent.mkdir(parents=True)
            dll.write_bytes(b"")

            with patch.dict(main_module.os.environ, {"APPDATA": temp_dir}):
                self.assertEqual(dll, clean_drawings.plugin_for(acad))


if __name__ == "__main__":
    unittest.main()
