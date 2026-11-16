import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import clean_drawings as clean

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "fetch_clean_cad_worker", ROOT / "build-config" / "fetch_clean_cad_worker.py")
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)


def _core_console(base, year):
    exe = Path(base) / f'AutoCAD {year}' / 'accoreconsole.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'')
    return exe


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'dll')
    return path


class PluginForTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.bundled = self.base / 'CleanCAD-bin'
        self.appdata = self.base / 'appdata'
        patcher = patch.object(clean, 'BUNDLED_WORKER_DIR', self.bundled)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {'APPDATA': str(self.appdata)})
        env.start()
        self.addCleanup(env.stop)

    def installed(self, framework, bundle='ElectricalCommands.bundle'):
        return _touch(self.appdata / 'Autodesk' / 'ApplicationPlugins' / bundle
                      / 'Contents' / framework / clean.WORKER_DLL)

    def test_bundled_worker_is_used_without_an_installed_plugin(self):
        dll = _touch(self.bundled / 'net8.0-windows' / clean.WORKER_DLL)
        self.assertEqual(clean.plugin_for(_core_console(self.base, 2025)), dll)

    def test_bundled_worker_wins_over_an_installed_plugin(self):
        dll = _touch(self.bundled / 'net48' / clean.WORKER_DLL)
        self.installed('net48')
        self.assertEqual(clean.plugin_for(_core_console(self.base, 2024)), dll)

    def test_installed_plugin_is_the_fallback_for_source_runs(self):
        dll = self.installed('net48', 'ElectricalCommands.CleanCADCommands.bundle')
        self.assertEqual(clean.plugin_for(_core_console(self.base, 2023)), dll)

    def test_missing_worker_does_not_ask_for_the_plugin(self):
        with self.assertRaises(FileNotFoundError) as caught:
            clean.plugin_for(_core_console(self.base, 2025))
        self.assertNotIn('Install the updated ACIES AutoCAD plugin', str(caught.exception))


def _release_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in entries:
            archive.writestr(name, b'x')
    return buffer.getvalue()


RELEASE_ENTRIES = [
    'ElectricalCommands.bundle/PackageContents.xml',
    'ElectricalCommands.bundle/Contents/lisp/cleanup.lsp',
    'ElectricalCommands.bundle/Contents/net48/AutoCADCommands.CleanCADCommands.dll',
    'ElectricalCommands.bundle/Contents/net48/AutoCADCommands.GeneralCommands.dll',
    'ElectricalCommands.bundle/Contents/net48/AutoCADCommands.Loader.dll',
    'ElectricalCommands.bundle/Contents/net48/Spire.Pdf.dll',
    'ElectricalCommands.bundle/Contents/net48/Magick.Native-Q16-x64.dll',
    'ElectricalCommands.bundle/Contents/net48/AutoCADCommands.CleanCADCommands.pdb',
    'ElectricalCommands.bundle/Contents/net48/x64/native.dll',
    'ElectricalCommands.bundle/Contents/net8.0-windows/AutoCADCommands.CleanCADCommands.dll',
    'ElectricalCommands.bundle/Contents/net8.0-windows/Magick.NET.Core.dll',
]


class FetchWorkerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.target = Path(temp.name) / 'CleanCAD-bin'

    def extract(self, entries):
        data = _release_zip(entries)
        with patch.object(fetch, 'PLUGIN_SHA256', hashlib.sha256(data).hexdigest()):
            fetch.extract(data, self.target)

    def test_copies_only_the_worker_and_its_libraries(self):
        self.extract(RELEASE_ENTRIES)
        files = sorted(p.relative_to(self.target).as_posix()
                       for p in self.target.rglob('*') if p.is_file())
        self.assertEqual(files, [
            'net48/AutoCADCommands.CleanCADCommands.dll',
            'net48/Magick.Native-Q16-x64.dll',
            'net48/Spire.Pdf.dll',
            'net48/x64/native.dll',
            'net8.0-windows/AutoCADCommands.CleanCADCommands.dll',
            'net8.0-windows/Magick.NET.Core.dll',
            'version.txt',
        ])
        self.assertTrue(fetch.is_current(self.target))

    def test_checksum_mismatch_is_refused(self):
        with self.assertRaises(ValueError):
            fetch.extract(_release_zip(RELEASE_ENTRIES), self.target)
        self.assertFalse(self.target.exists())

    def test_release_without_a_worker_is_refused_and_keeps_the_old_copy(self):
        self.extract(RELEASE_ENTRIES)
        with self.assertRaises(ValueError):
            self.extract([e for e in RELEASE_ENTRIES if 'net8.0-windows' not in e])
        self.assertTrue(fetch.is_current(self.target))

    def test_path_traversal_is_refused(self):
        with self.assertRaises(ValueError):
            fetch.worker_files(['ElectricalCommands.bundle/Contents/net48/../../evil.dll'])

    def test_pinned_release_is_a_combined_bundle_release(self):
        self.assertRegex(fetch.PLUGIN_VERSION, r'^v\d+\.\d+\.\d+$')
        self.assertIn(f'/{fetch.PLUGIN_VERSION}/', fetch.PLUGIN_URL)
        self.assertRegex(fetch.PLUGIN_SHA256, r'^[0-9a-f]{64}$')


if __name__ == '__main__':
    unittest.main()
