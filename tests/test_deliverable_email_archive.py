import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_page_email_attachment_backend import Api, _FakeMailItem, _FakeSelection, _FakeExplorer, _FakeApplication


class Attachment:
    def __init__(self, name, fail=False):
        self.FileName = name
        self.fail = fail

    def SaveAsFile(self, path):
        if self.fail:
            raise OSError('Attachment unavailable')
        Path(path).write_bytes(b'pdf content')


class DeliverableEmailArchiveTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '250597 Project'
        self.root.mkdir()
        self.context = dict(projectPath=str(self.root), deliverableName='Lighting Submittal',
                            category='Submittals', discipline='Electrical', date='2026-09-18')

    def save(self, attachments=(), count=1):
        mail = _FakeMailItem(subject='A' * 100)
        mail.Class = 43
        mail.Attachments = _FakeSelection(attachments)
        app = _FakeApplication(_FakeExplorer(_FakeSelection([mail] * count)))
        with patch.object(self.api, '_get_desktop_outlook_namespace', return_value=(app, None)), \
                patch.object(self.api, '_run_with_outlook_com', side_effect=lambda callback: callback()):
            return self.api.save_deliverable_outlook_email(self.context)

    def test_archives_message_and_attachments_from_discipline_path(self):
        discipline = self.root / 'Electrical'
        discipline.mkdir()
        self.context['projectPath'] = str(discipline)
        result = self.save([Attachment('lighting.pdf'), Attachment('lighting.pdf'), Attachment('../CON.pdf')])
        self.assertEqual(result['status'], 'success', result)
        folder = self.root / 'Submittals/Electrical/2026-09-18 Lighting Submittal'
        self.assertEqual(Path(result['folder']), folder)
        self.assertEqual(Path(result['emailPath']).suffix, '.msg')
        self.assertTrue((folder / 'lighting.pdf').exists())
        self.assertTrue((folder / 'lighting (2).pdf').exists())
        self.assertEqual(len(list(folder.iterdir())), 4)

    def test_repeat_save_keeps_existing_archive(self):
        first = self.save()
        original = Path(first['emailPath']).read_bytes()
        second = self.save()
        self.assertEqual(second['status'], 'success')
        self.assertNotEqual(first['folder'], second['folder'])
        self.assertEqual(Path(first['emailPath']).read_bytes(), original)

    def test_failed_attachment_leaves_no_partial_archive(self):
        result = self.save([Attachment('broken.pdf', fail=True)])
        self.assertEqual(result['status'], 'error')
        self.assertEqual(list((self.root / 'Submittals/Electrical').iterdir()), [])

    def test_requires_exactly_one_email(self):
        for count in (0, 2):
            self.assertEqual(self.save(count=count)['status'], 'error')
        self.assertFalse((self.root / 'Submittals').exists())

    def test_invalid_destination_and_date_are_rejected(self):
        for key, value in [('date', '2026-02-30'), ('category', '../escape'),
                           ('discipline', '../escape'), ('projectPath', ''), ('deliverableName', '')]:
            with self.subTest(key=key):
                old = self.context[key]
                self.context[key] = value
                self.assertEqual(self.save()['status'], 'error')
                self.context[key] = old

    def test_other_categories(self):
        for category, relative in [('RFI', 'RFI'), ('Correspondence', 'Documents/Correspondence')]:
            self.context['category'] = category
            result = self.save()
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(Path(result['folder']).parent, self.root / relative)


if __name__ == '__main__':
    unittest.main()
