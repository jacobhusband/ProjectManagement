"""Published sets move only on request, within PDF, without overwriting files."""
import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_deliverable_quick_access_pdf import Api


class PublishDestinationTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '251391 Example'
        self.pdf = self.root / 'pDf'
        self.pdf.mkdir(parents=True)
        self.source = Path(self.temp.name) / 'AutoCAD Plots' / 'set.pdf'
        self.source.parent.mkdir()
        self.source.write_bytes(b'%PDF-1.4\ncombined set')

    def move(self, name, create=False, project=None):
        return self.api.move_published_pdf(str(self.source), str(project or self.root), name, create)

    def test_lists_all_issue_folders_and_resolves_manual_dwg_ancestor(self):
        for name in ['2026-10-05 MEP IFP', 'Undated issue']:
            (self.pdf / name).mkdir()
        (self.pdf / 'other.pdf').write_bytes(b'pdf')
        dwg = self.root / 'Electrical' / 'E01.dwg'
        result = self.api.get_publish_pdf_destinations(str(self.source), str(dwg))
        self.assertEqual('success', result['status'])
        self.assertEqual(str(self.pdf), result['pdfFolder'])
        self.assertEqual({'2026-10-05 MEP IFP', 'Undated issue'}, {f['name'] for f in result['folders']})
        self.assertTrue(self.source.exists(), 'listing must leave the set in place')

    def test_moves_only_combined_set_to_existing_folder(self):
        folder = self.pdf / 'Existing issue'
        folder.mkdir()
        sheet = self.source.parent / 'E01.pdf'
        sheet.write_bytes(b'sheet')
        result = self.move(folder.name)
        self.assertEqual('success', result['status'])
        self.assertEqual(str(folder / 'set.pdf'), result['combinedPdfPath'])
        self.assertEqual(str(folder), result['openFolderPath'])
        self.assertFalse(self.source.exists())
        self.assertEqual(b'%PDF-1.4\ncombined set', (folder / 'set.pdf').read_bytes())
        self.assertTrue(sheet.exists())

    def test_creates_named_folder_and_moves_set(self):
        result = self.move('2026-10-05 MEP IFP', True)
        self.assertEqual('success', result['status'])
        self.assertTrue((self.pdf / '2026-10-05 MEP IFP' / 'set.pdf').exists())

    def test_existing_pdf_is_never_overwritten(self):
        folder = self.pdf / 'Existing'
        folder.mkdir()
        target = folder / 'set.pdf'
        target.write_bytes(b'previous issue')
        result = self.move(folder.name)
        self.assertEqual('error', result['status'])
        self.assertEqual(b'previous issue', target.read_bytes())
        self.assertTrue(self.source.exists())

    def test_new_folder_cannot_reuse_existing_name(self):
        (self.pdf / 'Existing').mkdir()
        self.assertEqual('error', self.move('Existing', True)['status'])
        self.assertTrue(self.source.exists())

    def test_invalid_names_and_missing_existing_folder_leave_source_intact(self):
        for name in ['', '../escape', '..', 'x/y', 'x\\y', 'CON', 'NUL.txt', 'bad:', 'trailing.', ' trailing']:
            with self.subTest(name=name):
                self.assertEqual('error', self.move(name, True)['status'])
                self.assertTrue(self.source.exists())
        self.assertEqual('error', self.move('Missing')['status'])
        self.assertFalse((self.pdf / 'Missing').exists())

    def test_copy_failure_cleans_partial_file_and_new_folder(self):
        def fail_copy(src, dst):
            dst.write(b'partial')
            raise OSError('Disk full')
        with patch('main.shutil.copyfileobj', side_effect=fail_copy):
            self.assertEqual('error', self.move('New issue', True)['status'])
        self.assertTrue(self.source.exists())
        self.assertFalse((self.pdf / 'New issue').exists())

    def test_locked_original_is_preserved_and_duplicate_removed(self):
        original_unlink = os.unlink
        def deny_source(path, *args, **kwargs):
            if os.path.normcase(path) == os.path.normcase(self.api._to_windows_extended_path(str(self.source))):
                raise PermissionError('PDF is open')
            return original_unlink(path, *args, **kwargs)
        with patch('main.os.unlink', side_effect=deny_source):
            result = self.move('New issue', True)
        self.assertEqual('error', result['status'])
        self.assertTrue(self.source.exists())
        self.assertFalse((self.pdf / 'New issue').exists())

    def test_missing_pdf_root_or_source_returns_error(self):
        self.pdf.rmdir()
        self.assertEqual('error', self.move('Issue', True)['status'])
        self.source.unlink()
        self.assertEqual('error', self.move('Issue', True)['status'])

    def test_cannot_move_into_folder_linked_outside_pdf(self):
        outside = Path(self.temp.name) / 'Outside'
        outside.mkdir()
        try:
            (self.pdf / 'Linked').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Windows symlinks require developer mode or elevated privileges')
        self.assertEqual('error', self.move('Linked')['status'])
        self.assertTrue(self.source.exists())
        self.assertFalse((outside / 'set.pdf').exists())


class PublishPreviousNamingTests(unittest.TestCase):
    """A new set follows the newest earlier issue's naming in the project PDF folder."""

    def setUp(self):
        self.api = Api.__new__(Api)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / '261164 Chick-Fil-A, Woodland, CA'
        self.pdf = self.root / 'PDF'
        self.dwg = self.root / 'Electrical' / 'E-Photometric.dwg'
        self.dwg.parent.mkdir(parents=True)
        self.dwg.write_bytes(b'dwg')
        for folder, name in [
            ('2026-09-08 Photometrics', 'Electrical Photometric Plan - CFA Woodland.pdf'),
            ('2026-09-18 Photometrics', 'Electrical Photometric - CFA Woodland.pdf'),
            ('_POC Coordination', 'Site Plan.pdf'),
        ]:
            (self.pdf / folder).mkdir(parents=True)
            (self.pdf / folder / name).write_bytes(b'%PDF-1.4')
        (self.pdf / '2026-09-18 Photometrics' / 'Mechanical - CFA Woodland.pdf').write_bytes(b'%PDF-1.4')
        self.source = base / 'AutoCAD Plots' / 'Chick-Fil-A, Woodland, CA - Electrical.pdf'
        self.source.parent.mkdir()
        self.source.write_bytes(b'%PDF-1.4\nnew set')
        # Pin "today" so date stamps refresh to a known date.
        original = Api._refresh_publish_name_dates
        pinned = patch.object(Api, '_refresh_publish_name_dates',
                              lambda api, name, today=None: original(api, name, datetime.date(2026, 11, 19)))
        pinned.start()
        self.addCleanup(pinned.stop)

    def refresh(self, name):
        return self.api._refresh_publish_name_dates(name)

    def test_destinations_suggest_newest_discipline_issue_names(self):
        result = self.api.get_publish_pdf_destinations(str(self.source), str(self.root), str(self.dwg))
        self.assertEqual('success', result['status'])
        self.assertEqual('Electrical Photometric - CFA Woodland.pdf', result['suggestedFileName'])
        self.assertEqual('Electrical Photometric - CFA Woodland.pdf', result['previousFileName'])
        self.assertEqual('2026-09-18 Photometrics', result['previousFolderName'])
        self.assertEqual('2026-11-19 Photometrics', result['suggestedFolderName'])

    def test_discipline_falls_back_to_the_combined_set_name(self):
        result = self.api.get_publish_pdf_destinations(str(self.source), str(self.root))
        self.assertEqual('Electrical Photometric - CFA Woodland.pdf', result['previousFileName'])
        mech = self.api._suggest_publish_pdf_names(str(self.pdf), 'Mechanical')
        self.assertEqual('Mechanical - CFA Woodland.pdf', mech['previousFileName'])

    def test_no_matching_issue_keeps_generated_names(self):
        result = self.api.get_publish_pdf_destinations(str(self.source), str(self.root), str(self.root / 'Plumbing' / 'P1.dwg'))
        self.assertEqual('', result['suggestedFileName'])
        self.assertEqual('', result['suggestedFolderName'])
        self.assertEqual({}, self.api._suggest_publish_pdf_names(str(self.pdf), ''))

    def test_date_stamps_in_previous_names_move_to_today(self):
        self.assertEqual('(ACIES)26459_CFA-Woodland_PSP-19_11-19-2026-Site Plan.pdf',
                         self.refresh('(ACIES)26459_CFA-Woodland_PSP-19_09-15-2026-Site Plan.pdf'))
        self.assertEqual('2026.11.19 E Set.pdf', self.refresh('2026.09.24 E Set.pdf'))
        self.assertEqual('2026_11_19 MEP IFP', self.refresh('2026_9_4 MEP IFP'))
        # Project numbers, sheet numbers, and impossible dates stay as they are.
        for name in ['261164 CFA - E-1.0.pdf', 'Rev 2026-13-45.pdf', 'Electrical Photometric - CFA Woodland.pdf']:
            self.assertEqual(name, self.refresh(name))

    def test_move_renames_set_without_overwriting(self):
        folder = self.pdf / '2026-09-18 Photometrics'
        clash = self.api.move_published_pdf(str(self.source), str(self.root), folder.name, False,
                                            'Electrical Photometric - CFA Woodland.pdf')
        self.assertEqual('error', clash['status'])
        self.assertEqual(b'%PDF-1.4', (folder / 'Electrical Photometric - CFA Woodland.pdf').read_bytes())
        self.assertTrue(self.source.exists())

        moved = self.api.move_published_pdf(str(self.source), str(self.root), '2026-11-19 Photometrics', True,
                                            'Electrical Photometric - CFA Woodland')
        self.assertEqual('success', moved['status'])
        target = self.pdf / '2026-11-19 Photometrics' / 'Electrical Photometric - CFA Woodland.pdf'
        self.assertEqual(str(target), moved['combinedPdfPath'])
        self.assertEqual(b'%PDF-1.4\nnew set', target.read_bytes())

    def test_move_rejects_invalid_file_names(self):
        for name in ['a/b.pdf', '..\\x.pdf', 'bad:.pdf', ' lead.pdf', 'CON.pdf', '.pdf', 'dot..pdf']:
            with self.subTest(name=name):
                result = self.api.move_published_pdf(str(self.source), str(self.root), 'New', True, name)
                self.assertEqual('error', result['status'])
                self.assertTrue(self.source.exists())
                self.assertFalse((self.pdf / 'New').exists())

    def test_save_as_dialog_starts_with_previous_issue_name(self):
        calls = []
        with patch.object(Api, '_create_file_dialog', side_effect=lambda t, **kw: calls.append(kw) or None, create=True), \
                patch.object(Api, '_get_file_dialog_type', return_value='SAVE', create=True):
            self.assertEqual('cancelled', self.api.select_publish_pdf_target(str(self.root), '', str(self.dwg))['status'])
        self.assertEqual('Electrical Photometric - CFA Woodland.pdf', calls[0]['save_filename'])


class PublishSaveAsTests(unittest.TestCase):
    """"Save set as..." moves the set to any chosen path, replacing only when asked."""

    def setUp(self):
        self.api = Api.__new__(Api)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / 'AutoCAD Plots' / 'Example - Electrical.pdf'
        self.source.parent.mkdir()
        self.source.write_bytes(b'%PDF-1.4\nnew set')
        self.folder = base / 'Anywhere'
        self.folder.mkdir()

    def place(self, name, replace=False):
        return self.api.place_published_pdf(str(self.source), str(self.folder / name), replace)

    def test_saves_under_new_name_in_any_folder(self):
        result = self.place('2026-10-19 MEP IFP.pdf')
        self.assertEqual('success', result['status'])
        target = self.folder / '2026-10-19 MEP IFP.pdf'
        self.assertEqual(str(target), result['combinedPdfPath'])
        self.assertEqual(str(self.folder), result['openFolderPath'])
        self.assertEqual(b'%PDF-1.4\nnew set', target.read_bytes())
        self.assertFalse(self.source.exists())

    def test_replaces_existing_pdf_when_confirmed(self):
        target = self.folder / 'Issued set.pdf'
        target.write_bytes(b'old set')
        result = self.place(target.name, replace=True)
        self.assertEqual('success', result['status'])
        self.assertIn('replaced', result['message'])
        self.assertEqual(b'%PDF-1.4\nnew set', target.read_bytes())
        self.assertFalse(self.source.exists())
        self.assertEqual(['Issued set.pdf'], [p.name for p in self.folder.iterdir()])

    def test_existing_pdf_kept_without_confirmation(self):
        target = self.folder / 'Issued set.pdf'
        target.write_bytes(b'old set')
        self.assertEqual('error', self.place(target.name)['status'])
        self.assertEqual(b'old set', target.read_bytes())
        self.assertTrue(self.source.exists())

    def test_locked_existing_pdf_is_left_alone(self):
        target = self.folder / 'Issued set.pdf'
        target.write_bytes(b'old set')
        with patch('main.os.replace', side_effect=PermissionError('open in Bluebeam')):
            result = self.place(target.name, replace=True)
        self.assertEqual('error', result['status'])
        self.assertIn('open in another program', result['message'])
        self.assertEqual(b'old set', target.read_bytes())
        self.assertTrue(self.source.exists())
        self.assertEqual(['Issued set.pdf'], [p.name for p in self.folder.iterdir()])

    def test_missing_folder_or_non_pdf_target_leaves_source(self):
        missing = self.api.place_published_pdf(str(self.source), str(self.folder / 'Gone' / 'x.pdf'))
        self.assertEqual('error', missing['status'])
        self.assertEqual('error', self.place('set.txt')['status'])
        self.assertTrue(self.source.exists())

    def test_default_name_matches_plot_script(self):
        dwg = r'M:\Client\2026\251391 San Mateo HS Pool\Electrical\E-1.0 Power.dwg'
        self.assertEqual('San Mateo HS Pool - Electrical.pdf', self.api._default_publish_pdf_name(dwg))
        self.assertEqual(
            'San Mateo HS Pool.pdf',
            self.api._default_publish_pdf_name('', r'M:\Client\2026\251391 San Mateo HS Pool'),
        )
        self.assertEqual('combined.pdf', self.api._default_publish_pdf_name())

    def test_dialog_starts_in_pdf_folder_and_flags_replacement(self):
        project = Path(self.temp.name) / '251391 Example'
        pdf = project / 'PDF'
        pdf.mkdir(parents=True)
        existing = pdf / 'Old.pdf'
        existing.write_bytes(b'old')
        calls = []

        def fake_dialog(dialog_type, **kwargs):
            calls.append(kwargs)
            return (str(existing),)

        with patch.object(Api, '_create_file_dialog', side_effect=fake_dialog, create=True), \
                patch.object(Api, '_get_file_dialog_type', return_value='SAVE', create=True):
            result = self.api.select_publish_pdf_target(str(project))
        self.assertEqual('success', result['status'])
        self.assertTrue(result['replace'])
        self.assertEqual(os.path.normcase(str(pdf)), os.path.normcase(calls[0]['directory']))
        self.assertEqual('Example.pdf', calls[0]['save_filename'])


if __name__ == '__main__':
    unittest.main()
