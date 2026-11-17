"""Exercise real archives and databases without importing the desktop application."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import data_transfer as transfer


class DataTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.destination = self.root / "destination"
        self.source.mkdir()
        self.destination.mkdir()
        self.directories = {"page_assets", "page_files"}
        self.names = ["tasks.json", "notes.json", "settings.json", "timesheets.json",
                      "templates.json", "checklists.json", "page_file_links.json",
                      "lighting_schedules.db", "page_assets", "page_files"]
        self.targets = {name: self.source / name for name in self.names}
        self.new_targets = {name: self.destination / name for name in self.names}
        self.archive = self.root / "transfer.zip"
        self.projects = [{"id": "251406", "name": "Café", "deliverables": [{"id": "dlv_1", "name": "Record documents"}]}]
        self.write("tasks.json", self.projects)
        self.write("notes.json", {"version": 2, "pages": [{"id": "n1", "html": "<p>Notes</p>"}]})
        self.write("settings.json", {"userName": "Jacob", "apiKey": "private-key", "googleAuth": {"accessToken": "private-token"}, "theme": "light"})
        self.write("timesheets.json", {"weeks": {"2026-11-16": [{"hours": 8}]}, "expenses": {}})
        self.write("templates.json", {"templates": [{"name": "Template"}]})
        self.write("checklists.json", {"checklists": [{"id": "c1"}]})
        self.write("page_file_links.json", {"file1": {"asset": "page_files/file.xlsx"}})
        for name in self.directories:
            (self.source / name).mkdir()
        (self.source / "page_assets" / "picture.png").write_bytes(b"image-data")
        (self.source / "page_files" / "file.xlsx").write_bytes(b"workbook-data")

    def write(self, name, value, folder=None):
        (folder or self.source).joinpath(name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def export(self):
        return transfer.export_archive(self.archive, self.targets, self.directories, "1.0", str(self.source))

    def stage(self):
        stage = self.root / "stage"
        stage.mkdir(exist_ok=True)
        manifest = transfer.stage_archive(self.archive, stage, self.new_targets, self.directories)
        return stage, manifest

    def rewrite_zip(self, mutate):
        with zipfile.ZipFile(self.archive) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        mutate(contents)
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, value in contents.items():
                archive.writestr(name, value)

    def test_round_trip_includes_live_sqlite_wal_and_managed_files(self):
        conn = sqlite3.connect(self.targets["lighting_schedules.db"])
        self.addCleanup(conn.close)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE schedules (id TEXT, payload TEXT)")
        conn.execute("INSERT INTO schedules VALUES ('1', 'saved-in-wal')")
        conn.commit()
        self.export()
        stage, manifest = self.stage()
        self.assertEqual("1.0", manifest["appVersion"])
        backup = transfer.restore_staged(stage, self.new_targets, self.directories, self.destination / "transfer_backups")
        self.assertTrue(Path(backup).is_file())
        self.assertEqual(self.projects, json.loads(self.new_targets["tasks.json"].read_text(encoding="utf-8")))
        self.assertEqual(b"image-data", (self.destination / "page_assets/picture.png").read_bytes())
        self.assertEqual(b"workbook-data", (self.destination / "page_files/file.xlsx").read_bytes())
        with closing(sqlite3.connect(self.new_targets["lighting_schedules.db"])) as restored:
            self.assertEqual("saved-in-wal", restored.execute("SELECT payload FROM schedules").fetchone()[0])

    def test_export_omits_credentials_but_local_recovery_preserves_original(self):
        self.export()
        with zipfile.ZipFile(self.archive) as archive:
            settings = json.loads(archive.read("settings.json"))
            self.assertEqual({"userName": "Jacob", "theme": "light"}, settings)
        old = '{ "apiKey": "destination-key", "userName": "Previous user" }'
        self.new_targets["settings.json"].write_text(old, encoding="utf-8")
        stage, _ = self.stage()
        backup = transfer.restore_staged(stage, self.new_targets, self.directories, self.destination / "transfer_backups")
        with zipfile.ZipFile(backup) as archive:
            self.assertEqual(old.encode(), archive.read("settings.json"))
        self.assertEqual("private-key", json.loads(self.targets["settings.json"].read_text())["apiKey"])

    def test_corrupt_checksum_rejected_before_existing_data_changes(self):
        self.export()
        old = b'[{"id":"existing"}]'
        self.new_targets["tasks.json"].write_bytes(old)
        self.rewrite_zip(lambda files: files.update({"tasks.json": b"[]"}))
        with self.assertRaisesRegex(ValueError, "damaged"):
            self.stage()
        self.assertEqual(old, self.new_targets["tasks.json"].read_bytes())

    def test_unsafe_unknown_duplicate_and_future_archives_are_rejected(self):
        for filename in ("../escape.txt", "page_assets/../../escape.txt", "C:/escape.txt", "page_files\\escape.txt",
                         "unmanaged.txt", "page_files/NUL.txt", "page_assets/COM1", "page_files"):
            with self.subTest(filename=filename):
                self.export()
                def mutate(files):
                    manifest = json.loads(files["manifest.json"])
                    import hashlib
                    manifest["files"][filename] = {"size": 1, "sha256": hashlib.sha256(b"x").hexdigest()}
                    files[filename] = b"x"
                    files["manifest.json"] = json.dumps(manifest)
                self.rewrite_zip(mutate)
                with self.assertRaises(ValueError):
                    self.stage()
        self.export()
        self.rewrite_zip(lambda files: files.update({"TASKS.JSON": files["tasks.json"]}))
        with self.assertRaises(ValueError):
            self.stage()
        self.export()
        def future(files):
            manifest = json.loads(files["manifest.json"])
            manifest["version"] = 999
            files["manifest.json"] = json.dumps(manifest)
        self.rewrite_zip(future)
        with self.assertRaisesRegex(ValueError, "supported"):
            self.stage()
        self.assertFalse((self.root / "escape.txt").exists())

    def test_invalid_json_or_database_does_not_replace_an_existing_export(self):
        self.export()
        original = self.archive.read_bytes()
        self.write("tasks.json", {"wrong": "shape"})
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(original, self.archive.read_bytes())
        self.write("tasks.json", self.projects)
        self.targets["lighting_schedules.db"].write_bytes(b"not a database")
        with self.assertRaises(sqlite3.DatabaseError):
            self.export()
        self.assertEqual(original, self.archive.read_bytes())

    def test_failed_import_rolls_back_files_and_directories(self):
        self.export()
        stage, _ = self.stage()
        self.write("tasks.json", [{"id": "original", "name": "Original"}], self.destination)
        original = self.new_targets["tasks.json"].read_bytes()
        (self.destination / "page_assets").mkdir()
        (self.destination / "page_assets/original.png").write_bytes(b"original-image")
        real_copytree = transfer.shutil.copytree
        failed = False
        def fail_once(source, destination, *args, **kwargs):
            nonlocal failed
            if Path(source) == stage / "page_files" and not failed:
                failed = True
                raise OSError("simulated disk error")
            return real_copytree(source, destination, *args, **kwargs)
        with patch.object(transfer.shutil, "copytree", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "Previous data was restored"):
                transfer.restore_staged(stage, self.new_targets, self.directories, self.destination / "transfer_backups")
        self.assertEqual(original, self.new_targets["tasks.json"].read_bytes())
        self.assertEqual(b"original-image", (self.destination / "page_assets/original.png").read_bytes())
        self.assertFalse((self.destination / "page_assets/picture.png").exists())

    def test_export_cannot_overwrite_managed_data(self):
        with self.assertRaises(ValueError):
            transfer.export_archive(self.source / "page_assets/export.zip", self.targets, self.directories)
        with self.assertRaises(ValueError):
            transfer.export_archive(self.targets["tasks.json"], self.targets, self.directories)


if __name__ == "__main__":
    unittest.main()
