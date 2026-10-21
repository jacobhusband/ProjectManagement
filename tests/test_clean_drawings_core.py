"""Opt-in live test: ACIES_TEST_CORE and ACIES_TEST_CLEAN_DLL must point to installed binaries."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from PIL import Image
import pymupdf as fitz

import clean_drawings as clean


@unittest.skipUnless(os.environ.get('ACIES_TEST_CORE') and os.environ.get('ACIES_TEST_CLEAN_DLL'), 'Core Console integration is opt-in')
class CoreCleanDrawingTests(unittest.TestCase):
    def test_inactive_layout_viewport_keeps_its_model_contents(self):
        with tempfile.TemporaryDirectory(prefix='acies-clean-inactive-viewport-') as temporary:
            root = Path(temporary)
            drawing = root / 'two-layouts.dwg'
            count = root / 'kept-lines.txt'
            fixture = root / 'fixture.scr'
            fixture.write_text(f'''(setvar "FILEDIA" 0)
(setvar "OSMODE" 0)
(command "_.LINE" "1000,1000" "1001,1001" "")
(command "_.LINE" "5000,5000" "5001,5001" "")
(command "_.LINE" "10000,10000" "10001,10001" "")
(setvar "TILEMODE" 0)
(setvar "CTAB" "Layout1")
(setq s (ssget "_X" '((0 . "VIEWPORT") (410 . "Layout1"))))
(if s (command "_.ERASE" s ""))
(command "_.MVIEW" "1,1" "11,11")
(command "_.MSPACE")
(command "_.ZOOM" "_C" "1000,1000" 20)
(command "_.PSPACE")
(setvar "CTAB" "Layout2")
(setq s (ssget "_X" '((0 . "VIEWPORT") (410 . "Layout2"))))
(if s (command "_.ERASE" s ""))
(command "_.MVIEW" "1,1" "11,11")
(command "_.MSPACE")
(command "_.ZOOM" "_C" "5000,5000" 20)
(command "_.PSPACE")
(command "_.QSAVE" "{drawing.as_posix()}")
_.QUIT
_Y
''', encoding='utf-8')
            probe = root / 'probe.scr'
            probe.write_text(f'''(setvar "SECURELOAD" 0)
_.NETLOAD
"{Path(os.environ['ACIES_TEST_CLEAN_DLL']).as_posix()}"
VP2PLHEADLESS
(setq f (open "{count.as_posix()}" "w"))
(setq s (ssget "_X" '((0 . "LINE") (410 . "Model"))))
(prin1 (if s (sslength s) 0) f)
(close f)
_.QUIT
_Y
''', encoding='utf-8')
            for script, inputs in [(fixture, []), (probe, ['/i', str(drawing)])]:
                result = subprocess.run([os.environ['ACIES_TEST_CORE'], *inputs, '/s', str(script)],
                                        cwd=root, capture_output=True, timeout=90,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.assertEqual(0, result.returncode, result.stdout[-3000:])
            self.assertEqual('2', count.read_text().strip(),
                             'Keep both layout regions and erase only the unrelated third line.\n' +
                             result.stdout.decode('utf-16-le', errors='replace'))

    def test_exploded_block_contents_keep_their_plotted_appearance(self):
        with tempfile.TemporaryDirectory(prefix='acies-clean-explode-') as temporary:
            root = Path(temporary)
            drawing = root / 'block.dwg'
            output = root / 'exploded.dwg'
            dump = root / 'entities.txt'
            fixture = root / 'fixture.scr'
            # Layer-0 and BYBLOCK content inherits from the insert, and MText indents
            # and absolute heights are drawing units that must scale with the insert.
            fixture.write_text(f'''(setvar "FILEDIA" 0)
(command "_.-LAYER" "_M" "TAG" "_C" "3" "" "_LW" "0.70" "" "_M" "OTHER" "_C" "5" "" "")
(setvar "CLAYER" "0")
(entmake '((0 . "LINE") (8 . "0") (10 0.0 0.0 0.0) (11 10.0 0.0 0.0)))
(setq a (entlast))
(entmake '((0 . "LINE") (8 . "OTHER") (62 . 0) (370 . -2) (10 0.0 2.0 0.0) (11 10.0 2.0 0.0)))
(setq b (entlast))
(entmake '((0 . "MTEXT") (100 . "AcDbEntity") (8 . "OTHER") (100 . "AcDbMText") (10 0.0 6.0 0.0) (40 . 1.0) (41 . 20.0) (71 . 1) (1 . "\\\\pxi10,l2,t4,6;RJ45\\\\P\\\\H2;Typ\\\\H0.5x;ical")))
(setq c (entlast))
(command "_.-BLOCK" "LBL" "0,0" a b c "")
(setvar "CLAYER" "TAG")
(command "_.-INSERT" "LBL" "2,2" 0.1 0.1 0)
(command "_.QSAVE" "{drawing.as_posix()}")
_.QUIT
_Y
''', encoding='utf-8')
            result = subprocess.run([os.environ['ACIES_TEST_CORE'], '/s', str(fixture)],
                                    cwd=root, capture_output=True, timeout=60,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(0, result.returncode, result.stdout[-3000:])
            clean.run_worker(os.environ['ACIES_TEST_CORE'], os.environ['ACIES_TEST_CLEAN_DLL'], drawing,
                             {'Operation': 'titleblock', 'Width': 36, 'Height': 24, 'Output': str(output)}, root)
            probe = root / 'probe.scr'
            probe.write_text(f'''(setq f (open "{dump.as_posix()}" "w"))
(setq s (ssget "_X" '((410 . "Model"))) i 0)
(while (< i (sslength s))
  (setq e (entget (ssname s i)) i (1+ i))
  (prin1 (list (cdr (assoc 0 e)) (cdr (assoc 8 e)) (cdr (assoc 62 e)) (cdr (assoc 370 e))
               (cdr (assoc 1 e)) (cdr (assoc 10 e))) f)
  (princ "\\n" f))
(close f)
_.QUIT
_Y
''', encoding='utf-8')
            result = subprocess.run([os.environ['ACIES_TEST_CORE'], '/i', str(output), '/s', str(probe)],
                                    cwd=root, capture_output=True, timeout=60,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(0, result.returncode, result.stdout[-3000:])
            rows = dump.read_text().splitlines()
            lines = sorted(row for row in rows if row.startswith('("LINE"'))
            self.assertEqual(2, len(lines), rows)
            # Layer-0 line moves to the insert's layer; the BYBLOCK line on another
            # layer takes the insert layer's color 3 and 0.70 mm lineweight.
            self.assertTrue(any(row.startswith('("LINE" "OTHER" 3 70 ') for row in lines), rows)
            self.assertTrue(any(row.startswith('("LINE" "TAG" nil nil ') for row in lines), rows)
            mtext = [row for row in rows if row.startswith('("MTEXT"')]
            self.assertEqual(1, len(mtext), rows)
            self.assertIn(r'\\pxi1,l0.2,t0.4,0.6;RJ45\\P\\H0.2;Typ\\H0.5x;ical', mtext[0])

    def test_external_raster_image_still_blocks_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='acies-clean-raster-') as temporary:
            root = Path(temporary)
            image = root / 'external.png'
            Image.new('RGB', (4, 4), 'white').save(image)
            drawing = root / 'image.dwg'
            script = root / 'make-image.scr'
            script.write_text(f'''(setvar "FILEDIA" 0)
(command "_.-IMAGE" "_ATTACH" "{image.as_posix()}" "0,0" 1 0)
(command "_.QSAVE" "{drawing.as_posix()}")
_.QUIT
_Y
''', encoding='utf-8')
            result = subprocess.run([os.environ['ACIES_TEST_CORE'], '/s', str(script)],
                                    cwd=root, capture_output=True, timeout=60,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(0, result.returncode)
            scan = clean.run_worker(os.environ['ACIES_TEST_CORE'], os.environ['ACIES_TEST_CLEAN_DLL'], drawing,
                                    {'Operation': 'scan', 'Files': [str(drawing)], 'Catalog': []}, root)
            self.assertEqual(1, len(scan['images']))
            self.assertEqual(str(image), scan['images'][0]['Resolved'])
            output = root / 'must-not-exist.dwg'
            with self.assertRaisesRegex(RuntimeError, 'Unsupported media'):
                clean.run_worker(os.environ['ACIES_TEST_CORE'], os.environ['ACIES_TEST_CLEAN_DLL'], drawing,
                                 {'Operation': 'titleblock', 'Width': 36, 'Height': 24, 'Output': str(output)}, root)
            self.assertFalse(output.exists())

    def test_fixed_boundary_sheet_binding_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix='acies-clean-integration-') as temporary:
            root = Path(temporary)
            (root / 'Xrefs').mkdir()
            (root / 'Electrical').mkdir()
            tb = (root / 'Xrefs' / 'x-TB.dwg').as_posix()
            sheet = (root / 'Electrical' / 'E01.dwg').as_posix()
            scripts = [f'''(setvar "FILEDIA" 0)
(command "_.RECTANG" "0,0" "36,24")
(command "_.WIPEOUT" "2,2" "4,2" "4,4" "2,4" "")
(command "_.LINE" "-10,-10" "-5,-5" "")
(command "_.LINE" "100,100" "110,110" "")
(command "_.QSAVE" "{tb}")
_.QUIT
_Y
''', f'''(setvar "FILEDIA" 0)
(command "_.LINE" "1,1" "5,5" "")
(setvar "TILEMODE" 0)
(command "_.-XREF" "_ATTACH" "{tb}" "0,0" 1 1 0)
(command "_.WIPEOUT" "8,8" "9,8" "9,9" "8,9" "")
(setvar "CECOLOR" "1")
(command "_.LINE" "10,10" "12,10" "")
(setvar "CECOLOR" "BYLAYER")
(command "_.QSAVE" "{sheet}")
_.QUIT
_Y
''']
            for index, text in enumerate(scripts):
                script = root / f'make-{index}.scr'
                script.write_text(text, encoding='utf-8')
                result = subprocess.run([os.environ['ACIES_TEST_CORE'], '/s', str(script)],
                                        cwd=root, capture_output=True, timeout=60,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.assertEqual(0, result.returncode)
            original = {p: p.read_bytes() for p in (Path(tb), Path(sheet))}
            scan = clean.run_worker(os.environ['ACIES_TEST_CORE'], os.environ['ACIES_TEST_CLEAN_DLL'], sheet,
                                    {'Operation': 'scan', 'Files': [sheet], 'Catalog': [tb]}, root)
            self.assertEqual([str(Path(tb))], scan['titleblocks'])
            self.assertEqual([], scan['media'], 'Wipeouts must not be classified as external media.')
            result = clean.run(root, {'titleblock': 'Xrefs/x-TB.dwg', 'drawings': ['Electrical/E01.dwg'], 'width': 36, 'height': 24},
                               os.environ['ACIES_TEST_CORE'], dll=Path(os.environ['ACIES_TEST_CLEAN_DLL']))
            report = json.loads((Path(result['output']) / 'cleanup-report.json').read_text())
            self.assertEqual(2, report['titleblockValidation']['modelEntities'])
            self.assertEqual(1, report['titleblockValidation']['wipeouts'])
            self.assertEqual(2, report['drawings'][0]['validation']['wipeouts'])
            self.assertEqual(0, report['drawings'][0]['validation']['externalReferences'])
            with fitz.open(Path(result['output']) / 'Review' / 'Original Set.pdf') as document:
                page = document[0]
                page.remove_rotation()
                self.assertEqual((2592, 1728), (round(page.rect.width), round(page.rect.height)))
                # The two-inch red paper-space line must plot at 1:1, at its
                # zero-offset position, and in black through the requested CTB.
                strokes = [(path, item) for path in page.get_drawings() for item in path['items']
                           if item[0] == 'l' and abs(item[1].x - 720) < 1 and abs(item[2].x - 864) < 1
                           and abs(item[1].y - 1008) < 1 and abs(item[2].y - 1008) < 1]
                self.assertTrue(strokes, 'Expected a 144-point line at the 1:1 paper-space position.')
                self.assertTrue(all(max(path['color']) < .01 for path, _ in strokes))
            for path, data in original.items():
                self.assertEqual(data, path.read_bytes())
            rejected_output = root / 'must-not-exist.dwg'
            with self.assertRaisesRegex(RuntimeError, 'did not complete'):
                clean.run_worker(os.environ['ACIES_TEST_CORE'], os.environ['ACIES_TEST_CLEAN_DLL'], sheet,
                                 {'Operation': 'sheet', 'Titleblock': str(root / 'wrong.dwg'),
                                  'Width': 36, 'Height': 24, 'Output': str(rejected_output)}, root)
            self.assertFalse(rejected_output.exists())


if __name__ == '__main__':
    unittest.main()
