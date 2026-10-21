import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import clean_drawings as clean


@unittest.skipUnless(os.environ.get('ACIES_TEST_CORE') and os.environ.get('ACIES_TEST_CLEAN_DLL'), 'Core Console integration is opt-in')
class TitleblockMarkTests(unittest.TestCase):
    def test_stamp_definitions_are_not_edited_and_nested_marks_are_removed(self):
        with tempfile.TemporaryDirectory(prefix='acies-marks-blocks-') as temporary:
            root = Path(temporary)
            drawing, output = root / 'titleblock.dwg', root / 'unmarked.dwg'
            dump = root / 'preserved.txt'
            fixture = root / 'fixture.scr'
            # All stamp geometry uses a marked layer. The old table-wide walk erased
            # that geometry as well as the inserts (and crashed on protected proxies).
            fixture.write_text(f'''(setvar "FILEDIA" 0)
(setvar "OSMODE" 0)
(command "_.-LAYER" "_M" "STAMP" "")
(command "_.LINE" "1,1" "2,2" "")
(command "_.-BLOCK" "EngineerStamp" "0,0" (entlast) "")
(command "_.LINE" "3,3" "4,4" "")
(command "_.-BLOCK" "UnusedStamp" "0,0" (entlast) "")
(setvar "CLAYER" "0")
(command "_.-INSERT" "EngineerStamp" "0,0" 1 1 0)
(command "_.-BLOCK" "Container" "0,0" (entlast) "")
(command "_.-INSERT" "Container" "0,0" 1 1 0)
(command "_.LINE" "10,10" "11,11" "")
(command "_.-BLOCK" "CompanyLogo" "0,0" (entlast) "")
(command "_.-INSERT" "CompanyLogo" "0,0" 1 1 0)
(command "_.-LAYER" "_LOCK" "0" "")
(command "_.QSAVE" "{drawing.as_posix()}")
_.QUIT
_Y
''')
            core = os.environ['ACIES_TEST_CORE']
            result = subprocess.run([core, '/s', str(fixture)], cwd=root, capture_output=True, timeout=90,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(0, result.returncode)
            original = drawing.read_bytes()
            removed = clean.run_worker(core, os.environ['ACIES_TEST_CLEAN_DLL'], drawing,
                                       {'Operation': 'remove-titleblock-marks', 'Output': str(output)}, root)
            self.assertEqual(1, len(removed['removed']))
            self.assertEqual('BlockReference', removed['removed'][0]['kind'])
            self.assertIn('EngineerStamp', removed['removed'][0]['source'])
            self.assertEqual(original, drawing.read_bytes())
            probe = root / 'probe.scr'
            probe.write_text(f'''(setq f (open "{dump.as_posix()}" "w"))
(foreach name '("EngineerStamp" "UnusedStamp" "CompanyLogo") (prin1 (cdr (assoc 0 (entget (cdr (assoc -2 (tblsearch "BLOCK" name)))))) f) (princ "\\n" f))
(prin1 (logand 4 (cdr (assoc 70 (tblsearch "LAYER" "0")))) f)
(close f)
_.QUIT
_Y
''')
            result = subprocess.run([core, '/i', str(output), '/s', str(probe)], cwd=root,
                                    capture_output=True, timeout=90,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(0, result.returncode)
            self.assertEqual(['"LINE"', '"LINE"', '"LINE"', '4'], dump.read_text().splitlines())

    def test_named_stamp_removed_logo_preserved_and_original_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='acies-marks-test-') as temporary:
            root = Path(temporary)
            drawing = root / 'titleblock.dwg'
            output = root / 'unmarked.dwg'
            script = root / 'fixture.scr'
            script.write_text(f'''(setvar "FILEDIA" 0)
(command "_.LINE" "1,1" "2,2" "")
(command "_.-BLOCK" "EngineerStamp" "0,0" (entlast) "")
(command "_.-INSERT" "EngineerStamp" "0,0" 1 1 0)
(command "_.LINE" "10,10" "11,11" "")
(command "_.-BLOCK" "CompanyLogo" "0,0" (entlast) "")
(command "_.-INSERT" "CompanyLogo" "0,0" 1 1 0)
(command "_.QSAVE" "{drawing.as_posix()}")
_.QUIT
_Y
''')
            result = subprocess.run([os.environ['ACIES_TEST_CORE'], '/s', str(script)], cwd=root, capture_output=True, timeout=90,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(0, result.returncode)
            original = drawing.read_bytes()
            removed = clean.run_worker(os.environ['ACIES_TEST_CORE'], os.environ['ACIES_TEST_CLEAN_DLL'], drawing,
                                       {'Operation': 'remove-titleblock-marks', 'Output': str(output)}, root)
            self.assertEqual(1, len(removed['removed']))
            self.assertIn('EngineerStamp', removed['removed'][0]['source'])
            self.assertEqual(original, drawing.read_bytes())
            counts = clean.run_worker(os.environ['ACIES_TEST_CORE'], os.environ['ACIES_TEST_CLEAN_DLL'], output,
                                      {'Operation': 'verify'}, root)
            self.assertEqual(1, counts['modelEntities'])


if __name__ == '__main__':
    unittest.main()
