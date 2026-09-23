import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import json
import zipfile
from pathlib import Path

# The CAD scripts skip their file pickers when this is set, so no dialog can open during tests.
os.environ["ACIES_NONINTERACTIVE"] = "1"


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "removeXREFPaths.ps1"


@unittest.skipUnless(sys.platform == "win32", "removeXREFPaths.ps1 behavior tests are Windows-only")
class RemoveXrefPathsBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if cls.powershell is None:
            raise unittest.SkipTest("powershell.exe is required to validate removeXREFPaths.ps1")

    def _write_file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _run_script(self, selected_paths, discipline_short="E"):
        files_list_path = selected_paths[0].parent / "__selected_files.txt"
        files_list_path.write_text(
            "\n".join(str(path) for path in selected_paths),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                self.powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT_PATH),
                "-AcadCore",
                self.powershell,
                "-DisciplineShort",
                discipline_short,
                "-FilesListPath",
                str(files_list_path),
                "-SkipAcad",
                "1",
                "-StripXrefs",
                "0",
                "-SetByLayer",
                "0",
                "-Purge",
                "0",
                "-Audit",
                "0",
                "-HatchColor",
                "0",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result, output

    def _run_script_with_manifest(self, manifest_path, discipline_short="E", env=None):
        result = subprocess.run(
            [
                self.powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT_PATH),
                "-AcadCore",
                self.powershell,
                "-DisciplineShort",
                discipline_short,
                "-SourceManifestPath",
                str(manifest_path),
                "-SkipAcad",
                "1",
                "-StripXrefs",
                "0",
                "-SetByLayer",
                "0",
                "-Purge",
                "0",
                "-Audit",
                "0",
                "-HatchColor",
                "0",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=env,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result, output

    def _same_path(self, expected, actual):
        # The script reports long paths; %TEMP% may be an 8.3 alias (C:\Users\RUNNER~1).
        self.assertEqual(Path(expected).resolve(), Path(actual).resolve())

    def _short_path(self, path):
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
        return buffer.value if 0 < length < len(buffer) else str(path)

    def _read_compare_pairs(self, output):
        marker = "PROGRESS: DWG_COMPARE_PAIR:"
        return [
            json.loads(line.split(marker, 1)[1].strip())
            for line in output.splitlines()
            if marker in line
        ]

    def test_arch_source_stages_into_xrefs_and_archives_existing_target(self):
        with tempfile.TemporaryDirectory(prefix="acies-remove-xrefs-arch-") as temp_dir:
            project_root = Path(temp_dir) / "260243 Example"
            arch_source = project_root / "Arch" / "A01-01 plan.dwg"
            canonical_target = project_root / "Xrefs" / "A01-01 (E).dwg"
            self._write_file(arch_source, "arch-source")
            self._write_file(canonical_target, "existing-target")

            result, output = self._run_script([arch_source])

            self.assertEqual(0, result.returncode, msg=output)
            self.assertTrue(arch_source.exists())
            self.assertEqual("arch-source", canonical_target.read_text(encoding="utf-8"))
            self.assertFalse(list((project_root / "Xrefs").glob("__incoming__*.dwg")))
            archived_targets = list((project_root / "Xrefs" / "Archive").glob("A01-01 (E)_*.dwg"))
            self.assertEqual(1, len(archived_targets), msg=output)
            self.assertEqual("existing-target", archived_targets[0].read_text(encoding="utf-8"))
            self.assertIn("Staged Arch source in Xrefs as __incoming__", output)
            self.assertIn("Archived existing file to A01-01 (E)_", output)
            compare_pairs = self._read_compare_pairs(output)
            self.assertEqual(1, len(compare_pairs), msg=output)
            self._same_path(canonical_target, compare_pairs[0]["newPath"])
            self._same_path(archived_targets[0], compare_pairs[0]["oldPath"])
            self.assertEqual("A01-01", compare_pairs[0]["label"])

    def test_manifest_file_source_stages_into_xrefs(self):
        with tempfile.TemporaryDirectory(prefix="acies-remove-xrefs-manifest-file-") as temp_dir:
            project_root = Path(temp_dir) / "260247 Example"
            arch_source = project_root / "Arch" / "A05-05 plan.dwg"
            canonical_target = project_root / "Xrefs" / "A05-05 (E).dwg"
            self._write_file(arch_source, "manifest-arch-source")
            manifest_path = project_root / "manifest.json"
            manifest_path.write_text(
                json.dumps([{"kind": "file", "path": str(arch_source)}]),
                encoding="utf-8",
            )

            result, output = self._run_script_with_manifest(manifest_path)

            self.assertEqual(0, result.returncode, msg=output)
            self.assertEqual("manifest-arch-source", canonical_target.read_text(encoding="utf-8"))
            self.assertIn("Using 1 DWG source(s) from workflow selection.", output)
            self.assertIn("Staged Arch source in Xrefs as __incoming__", output)

    def test_multiple_replacements_report_one_compare_pair_per_drawing(self):
        with tempfile.TemporaryDirectory(prefix="acies-remove-xrefs-compare-many-") as temp_dir:
            project_root = Path(temp_dir) / "260249 Example"
            sources = [
                project_root / "Arch" / "A01-01 plan.dwg",
                project_root / "Arch" / "A02-02 plan.dwg",
            ]
            targets = [
                project_root / "Xrefs" / "A01-01 (E).dwg",
                project_root / "Xrefs" / "A02-02 (E).dwg",
            ]
            for index, source in enumerate(sources, start=1):
                self._write_file(source, f"new-{index}")
            for index, target in enumerate(targets, start=1):
                self._write_file(target, f"old-{index}")

            result, output = self._run_script(sources)

            self.assertEqual(0, result.returncode, msg=output)
            compare_pairs = self._read_compare_pairs(output)
            self.assertEqual(2, len(compare_pairs), msg=output)
            self.assertEqual({"A01-01", "A02-02"}, {pair["label"] for pair in compare_pairs})
            self.assertEqual(
                {target.resolve() for target in targets},
                {Path(pair["newPath"]).resolve() for pair in compare_pairs},
            )

    def test_manifest_zip_entry_extracts_and_stages_into_project_xrefs(self):
        with tempfile.TemporaryDirectory(prefix="acies-remove-xrefs-manifest-zip-") as temp_dir:
            project_root = Path(temp_dir) / "260248 Example"
            arch_folder = project_root / "Arch" / "Latest"
            arch_folder.mkdir(parents=True, exist_ok=True)
            zip_path = arch_folder / "CAD.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("Backgrounds/A06-06 plan.dwg", "zip-arch-source")
            canonical_target = project_root / "Xrefs" / "A06-06 (E).dwg"
            manifest_path = project_root / "manifest.json"
            manifest_path.write_text(
                json.dumps([
                    {
                        "kind": "zipEntry",
                        "zipPath": str(zip_path),
                        "entryName": "Backgrounds/A06-06 plan.dwg",
                        "projectRoot": str(project_root),
                        "displayPath": f"{zip_path}::Backgrounds/A06-06 plan.dwg",
                    }
                ]),
                encoding="utf-8",
            )

            result, output = self._run_script_with_manifest(manifest_path)

            self.assertEqual(0, result.returncode, msg=output)
            self.assertEqual("zip-arch-source", canonical_target.read_text(encoding="utf-8"))
            self.assertFalse(list((project_root / "Xrefs").glob("__incoming__*.dwg")))
            self.assertIn("Preparing Arch ZIP source for Xrefs transfer: A06-06 plan.dwg", output)
            self.assertIn("Staged Arch ZIP source in Xrefs as __incoming__", output)

    def test_manifest_zip_entry_stages_when_temp_is_a_short_path(self):
        # Windows gives long profile names an 8.3 %TEMP% and .NET expands those
        # names, so ZIP staging has to compare paths in the same long form.
        with tempfile.TemporaryDirectory(prefix="acies-remove-xrefs-short-temp-") as temp_dir:
            short_temp = self._short_path(temp_dir)
            if short_temp.casefold() == str(temp_dir).casefold():
                self.skipTest("This volume does not create 8.3 names")
            project_root = Path(temp_dir) / "260250 Example"
            arch_folder = project_root / "Arch"
            arch_folder.mkdir(parents=True)
            zip_path = arch_folder / "CAD.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("A07-07 plan.dwg", "short-temp-source")
            manifest_path = project_root / "manifest.json"
            manifest_path.write_text(
                json.dumps([{
                    "kind": "zipEntry",
                    "zipPath": str(zip_path),
                    "entryName": "A07-07 plan.dwg",
                    "projectRoot": str(project_root),
                }]),
                encoding="utf-8",
            )

            result, output = self._run_script_with_manifest(
                manifest_path, env={**os.environ, "TEMP": short_temp, "TMP": short_temp}
            )

            self.assertEqual(0, result.returncode, msg=output)
            self.assertNotIn("escapes staging folder", output)
            canonical_target = project_root / "Xrefs" / "A07-07 (E).dwg"
            self.assertEqual("short-temp-source", canonical_target.read_text(encoding="utf-8"))

    def test_xrefs_source_is_archived_before_canonical_target_is_created(self):
        with tempfile.TemporaryDirectory(prefix="acies-remove-xrefs-source-") as temp_dir:
            project_root = Path(temp_dir) / "260244 Example"
            xrefs_source = project_root / "Xrefs" / "A02-02 background.dwg"
            canonical_target = project_root / "Xrefs" / "A02-02 (E).dwg"
            self._write_file(xrefs_source, "xrefs-source")

            result, output = self._run_script([xrefs_source])

            self.assertEqual(0, result.returncode, msg=output)
            self.assertFalse(xrefs_source.exists())
            self.assertTrue(canonical_target.exists())
            self.assertEqual("xrefs-source", canonical_target.read_text(encoding="utf-8"))
            self.assertFalse(list((project_root / "Xrefs").glob("__incoming__*.dwg")))
            archived_sources = list((project_root / "Xrefs" / "Archive").glob("A02-02 background_*.dwg"))
            self.assertEqual(1, len(archived_sources), msg=output)
            self.assertEqual("xrefs-source", archived_sources[0].read_text(encoding="utf-8"))
            self.assertIn("Staged Xrefs source in Xrefs as __incoming__", output)
            self.assertIn("Archived selected Xrefs source to A02-02 background_", output)

    def test_xrefs_source_already_named_as_canonical_target_is_recreated_after_backup(self):
        with tempfile.TemporaryDirectory(prefix="acies-remove-xrefs-canonical-") as temp_dir:
            project_root = Path(temp_dir) / "260245 Example"
            canonical_target = project_root / "Xrefs" / "A03-03 (E).dwg"
            self._write_file(canonical_target, "current-canonical")

            result, output = self._run_script([canonical_target])

            self.assertEqual(0, result.returncode, msg=output)
            self.assertTrue(canonical_target.exists())
            self.assertEqual("current-canonical", canonical_target.read_text(encoding="utf-8"))
            self.assertFalse(list((project_root / "Xrefs").glob("__incoming__*.dwg")))
            archived_sources = list((project_root / "Xrefs" / "Archive").glob("A03-03 (E)_*.dwg"))
            self.assertEqual(1, len(archived_sources), msg=output)
            self.assertEqual("current-canonical", archived_sources[0].read_text(encoding="utf-8"))
            self.assertIn("Archived selected Xrefs source to A03-03 (E)_", output)

    def test_xrefs_archive_selection_is_rejected_without_creating_a_new_target(self):
        with tempfile.TemporaryDirectory(prefix="acies-remove-xrefs-archive-") as temp_dir:
            project_root = Path(temp_dir) / "260246 Example"
            archived_source = project_root / "Xrefs" / "Archive" / "A04-04 old.dwg"
            canonical_target = project_root / "Xrefs" / "A04-04 (E).dwg"
            self._write_file(archived_source, "archived-copy")

            result, output = self._run_script([archived_source])

            self.assertEqual(0, result.returncode, msg=output)
            self.assertTrue(archived_source.exists())
            self.assertEqual("archived-copy", archived_source.read_text(encoding="utf-8"))
            self.assertFalse(canonical_target.exists())
            self.assertIn(
                "Selected DWG is already inside the Xrefs\\Archive folder.",
                output,
            )
            self.assertIn("ERROR: 1 of 1 file(s) failed to process.", output)

    def test_cleanup_lisp_recolors_hatches_via_chprop_not_entmod(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")

        # Hatch recolor must go through CHPROP; hand-editing HATCH entity data
        # with entmod produced malformed entities that triggered AutoCAD
        # recovery prompts when the saved drawings were reopened.
        self.assertIn('(command "_.CHPROP" target "" "_Color" "9" "")', text)
        self.assertNotIn("(entmod entData)", text)
        self.assertNotIn("(cons 62 9)", text)
        # Space switching uses setvar instead of layout-switch commands.
        self.assertIn('(setvar "CTAB" "Model")', text)
        self.assertNotIn('(command "_.MODEL")', text)

    def test_script_verifies_processed_drawings_reopen_cleanly(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("function Invoke-AcadCoreScript {", text)
        self.assertIn("function Get-AuditErrorCount {", text)
        self.assertIn("function Get-AcadOutputFailureSignal {", text)
        self.assertIn("verify_AUDIT.scr", text)
        self.assertIn("Verified clean on reopen:", text)
        self.assertIn("AUDIT error(s) on reopen.", text)

    def test_script_offers_zip_entries_in_manual_selection(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('function Show-DwgFileDialog {', text)
        self.assertIn('[string]$SourceManifestPath = ""', text)
        self.assertIn('function Read-SourceManifest {', text)
        self.assertIn('function Resolve-SourceItemToWorkingSource {', text)
        self.assertIn('Write-Host "PROGRESS: Opening DWG file picker..."', text)
        self.assertIn('DWG files and ZIP archives (*.dwg;*.zip)|*.dwg;*.zip', text)
        self.assertIn('Show-ZipDwgDialog -ZipPath $_', text)
        self.assertIn('$list.CheckedItems', text)
        self.assertIn("Kind = 'zipEntry'", text)
        self.assertNotIn("ZIP source selected. Extracting archive", text)
        self.assertNotIn('"{0}_Prepared" -f $zipBaseName', text)

    def test_zip_traversal_does_not_replace_existing_background(self):
        with tempfile.TemporaryDirectory(prefix="acies-xref-unsafe-zip-") as temporary:
            root = Path(temporary)
            archive = root / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('A01-01.dwg', 'selected')
                bundle.writestr('../escape.dwg', 'unsafe')
            target = root / 'Xrefs/A01-01 (E).dwg'
            target.parent.mkdir()
            target.write_text('existing')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps([{'kind': 'zipEntry', 'zipPath': str(archive),
                'entryName': 'A01-01.dwg', 'projectRoot': str(root)}]))
            result, output = self._run_script_with_manifest(manifest)
            self.assertIn('Unsafe ZIP entry', output)
            self.assertEqual('existing', target.read_text())
            self.assertFalse((root / 'escape.dwg').exists())


if __name__ == "__main__":
    unittest.main()
