"""Opt-in real DWG tests: set ACIES_TEST_CORE to an installed accoreconsole.exe."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('ACIES_TEST_CORE'), 'Core Console integration is opt-in')
class PrepareXrefsCoreTests(unittest.TestCase):
    def core(self, folder, text, drawing=None):
        script = folder / 'test.scr'
        script.write_text(text + '\n_.QUIT\n_Y\n', encoding='utf-8')
        args = [os.environ['ACIES_TEST_CORE']]
        if drawing:
            args += ['/i', str(drawing)]
        result = subprocess.run(args + ['/s', str(script)], cwd=folder, capture_output=True,
                                timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(0, result.returncode, result.stdout[-4000:])
        return result.stdout.decode('utf-16-le', errors='replace')

    def fixture(self, folder, name, commands):
        drawing = folder / name
        output = self.core(folder, '(setvar "FILEDIA" 0)\n(setvar "OSMODE" 0)\n' + commands +
                  f'\n(command "_.QSAVE" "{drawing.as_posix()}")')
        self.assertTrue(drawing.is_file(), output)
        return drawing

    def run_tool(self, source, manifest=False):
        args = ['powershell.exe', '-NoProfile', '-File', str(ROOT / 'scripts/removeXREFPaths.ps1'),
                '-AcadCore', os.environ['ACIES_TEST_CORE'], '-DisciplineShort', 'E',
                '-StripXrefs', '0', '-SetByLayer', '0', '-HatchColor', '0', '-Audit', '1', '-Purge', '1']
        if manifest:
            args += ['-SourceManifestPath', str(source)]
        else:
            listing = source.parent / 'files.txt'
            listing.write_text(str(source), encoding='utf-8')
            args += ['-FilesListPath', str(listing)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=180)
        return result.stdout + result.stderr

    def test_zip_nested_refs_explode_but_local_blocks_and_originals_survive(self):
        with tempfile.TemporaryDirectory(prefix='acies-xref-core-') as temporary:
            project = Path(temporary)
            arch = project / 'Arch'
            arch.mkdir()
            leaf = self.fixture(arch, 'leaf.dwg', '(command "_.LINE" "0,0" "1,0" "")')
            child = self.fixture(arch, 'child.dwg',
                '(command "_.-XREF" "_Attach" "leaf.dwg" "10,0" 1 1 0)')
            source = self.fixture(arch, 'A01-01.dwg',
                '(command "_.-XREF" "_Attach" "child.dwg" "100,0" 1 1 0)\n'
                '(command "_.CIRCLE" "0,0" 2)\n'
                '(command "_.-BLOCK" "LOCAL" "0,0" "_L" "")\n'
                '(command "_.-INSERT" "LOCAL" "0,0" 1 1 0)')
            archive = arch / 'received.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                for drawing in (leaf, child, source):
                    bundle.write(drawing, 'Package/' + drawing.name)
            # The archive alone must supply the dependency tree.
            leaf.unlink()
            child.unlink()
            before = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest = project / 'manifest.json'
            manifest.write_text(json.dumps([{'kind': 'zipEntry', 'zipPath': str(archive),
                'entryName': 'Package/A01-01.dwg', 'projectRoot': str(project)}]))
            output = self.run_tool(manifest, manifest=True)
            self.assertIn('ACIES_XREF_PREPARED: 2 bound; 2 modelspace references exploded.', output)
            self.assertIn('Verified clean on reopen', output)
            target = project / 'Xrefs/A01-01 (E).dwg'
            self.assertTrue(target.is_file(), output)
            report = project / 'probe.txt'
            self.core(project, f'''(setq f (open "{report.as_posix()}" "w"))
(setq s (ssget "_X" '((0 . "LINE") (410 . "Model"))))
(prin1 (if s (sslength s) 0) f)
(write-line "" f)
(prin1 (cdr (assoc 10 (entget (ssname s 0)))) f)
(write-line "" f)
(setq s (ssget "_X" '((0 . "INSERT") (2 . "LOCAL") (410 . "Model"))))
(prin1 (if s (sslength s) 0) f)
(close f)''', target)
            self.assertEqual(['1', '(110.0 0.0 0.0)', '1'], report.read_text().splitlines())
            self.assertEqual(before, hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual([target], list((project / 'Xrefs').glob('*.dwg')))

    def test_missing_reference_is_detached_and_source_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix='acies-xref-missing-') as temporary:
            project = Path(temporary)
            arch = project / 'Arch'
            arch.mkdir()
            leaf = self.fixture(arch, 'missing.dwg', '(command "_.LINE" "0,0" "1,0" "")')
            source = self.fixture(arch, 'A02-02.dwg',
                '(command "_.-XREF" "_Attach" "missing.dwg" "0,0" 1 1 0)')
            leaf.unlink()
            target = project / 'Xrefs/A02-02 (E).dwg'
            target.parent.mkdir()
            target.write_bytes(b'existing background')
            before = source.read_bytes()
            output = self.run_tool(source)
            self.assertIn('Detached missing XREF', output)
            self.assertIn('Verified clean on reopen', output)
            self.assertNotEqual(b'existing background', target.read_bytes())
            self.assertEqual(before, source.read_bytes())
            archived = list((target.parent / 'Archive').glob('*.dwg'))
            self.assertEqual(1, len(archived))
            self.assertEqual(b'existing background', archived[0].read_bytes())
            report = project / 'missing.txt'
            self.core(project, f'''(setq f (open "{report.as_posix()}" "w"))
(prin1 (tblsearch "BLOCK" "missing") f)
(close f)''', target)
            self.assertEqual('nil', report.read_text().strip())

    def test_paperspace_reference_is_bound_but_not_exploded(self):
        with tempfile.TemporaryDirectory(prefix='acies-xref-paper-') as temporary:
            project = Path(temporary)
            arch = project / 'Arch'
            arch.mkdir()
            self.fixture(arch, 'leaf.dwg', '(command "_.LINE" "0,0" "1,0" "")')
            source = self.fixture(arch, 'A03-03.dwg',
                '(command "_.-XREF" "_Attach" "leaf.dwg" "10,0" 2 2 90)\n'
                '(setvar "TILEMODE" 0)\n'
                '(setvar "CTAB" "Layout1")\n'
                '(entmakex \'((0 . "INSERT") (2 . "leaf") (10 0.0 0.0 0.0) (410 . "Layout1")))')
            output = self.run_tool(source)
            self.assertIn('ACIES_XREF_PREPARED: 1 bound; 1 modelspace references exploded.', output)
            target = project / 'Xrefs/A03-03 (E).dwg'
            report = project / 'paper.txt'
            self.core(project, f'''(setq f (open "{report.as_posix()}" "w"))
(setq s (ssget "_X" '((0 . "INSERT") (410 . "Layout1"))))
(prin1 (if s (sslength s) 0) f)
(write-line "" f)
(setq s (ssget "_X" '((0 . "LINE") (410 . "Model"))))
(prin1 (cdr (assoc 11 (entget (ssname s 0)))) f)
(close f)''', target)
            self.assertEqual(['1', '(10.0 2.0 0.0)'], report.read_text().splitlines())


if __name__ == '__main__':
    unittest.main()
