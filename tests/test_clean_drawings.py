import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fitz
import clean_drawings as clean


class CleanDrawingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # clean_drawings compares resolved paths. Resolve the fixture too, since
        # %TEMP% can be an 8.3 alias such as C:\Users\RUNNER~1 on build machines.
        base = Path(self.temp.name).resolve()
        self.root = base / 'Project'
        (self.root / 'Electrical').mkdir(parents=True)
        (self.root / 'Xrefs').mkdir()
        self.tb = self.root / 'Xrefs' / 'x-TB.dwg'
        self.sheet = self.root / 'Electrical' / 'E01.dwg'
        self.tb.write_bytes(b'titleblock original')
        self.sheet.write_bytes(b'sheet original')
        self.selection = {'titleblock': 'Xrefs/x-TB.dwg', 'drawings': ['Electrical/E01.dwg'], 'width': 36, 'height': 24}
        self.calls = []
        self.media = []
        self.pdfs = []
        self.images = []
        self.fail_operation = ''
        self.work = base / 'worker'
        self.work.mkdir()
        def comparison(original, reference, cleaned, output, **kwargs):
            Path(output).mkdir()
            (Path(output) / 'Comparison.pdf').write_bytes(b'review fixture')
            return {'status': 'match_within_tolerance'}
        self.comparison = patch.object(clean, 'compare_sets', side_effect=comparison)
        self.compare_mock = self.comparison.start()
        self.addCleanup(self.comparison.stop)

    def worker(self, acad, dll, drawing, job, workspace):
        op = job['Operation']
        self.calls.append(op)
        if op == self.fail_operation:
            raise RuntimeError('simulated failure')
        if op == 'scan':
            return {'files': [str(self.tb), str(self.sheet)], 'references': [], 'media': self.media, 'pdfs': self.pdfs, 'images': self.images}
        if op == 'plot-review':
            return {'pages': [{'layout': 'E01', 'file': str(Path(job['Output']) / '0000.pdf')}]}
        if op in ('titleblock', 'sheet', 'embed-media', 'remove-titleblock-marks'):
            self.assertTrue(clean._inside(drawing, workspace))
            self.assertTrue(clean._inside(job['Output'], workspace))
            Path(job['Output']).write_bytes(b'cleaned')
        return {'modelEntities': 1, 'paperEntities': 1, 'externalReferences': 0}

    def test_pdf_assets_are_staged_converted_and_reopened_before_cleanup(self):
        source = self.root / 'form.pdf'
        with fitz.open() as document:
            document.new_page().insert_text((72, 72), 'Energy form')
            document.save(source)
        original = source.read_bytes()
        self.pdfs = [{'Owner': str(self.sheet), 'Resolved': str(source), 'Path': str(source), 'Handle': '1', 'Page': '1'}]
        def worker(*args):
            job, workspace = args[3], args[4]
            if job['Operation'] == 'prepare':
                target = Path(job['PdfCopies'][str(source)])
                self.assertTrue(clean._inside(target, workspace))
                self.assertEqual(original, target.read_bytes())
            return self.worker(*args)
        result = self.run_job(worker)
        self.assertEqual(original, source.read_bytes())
        self.assertLess(self.calls.index('embed-media'), self.calls.index('titleblock'))
        self.assertLess(self.calls.index('verify-media'), self.calls.index('titleblock'))
        self.assertTrue((Path(result['output']) / 'Review/Comparison.pdf').exists())
        self.assertFalse((Path(result['output']) / 'form.pdf').exists())

    def test_unexpected_visual_changes_are_delivered_for_review_not_marked_match(self):
        def comparison(*args, **kwargs):
            Path(args[3]).mkdir()
            return {'status': 'review_required'}
        self.compare_mock.side_effect = comparison
        result = self.run_job()
        self.assertTrue(result['output'].endswith('_REVIEW_REQUIRED'))
        self.assertIn('Review required', result['comparisonWarning'])
        report = json.loads((Path(result['output']) / 'cleanup-report.json').read_text())
        self.assertEqual('review_required', report['status'])

    def test_failed_media_conversion_does_not_deliver(self):
        source = self.root / 'logo.png'
        source.write_bytes(b'fixture')
        self.images = [{'Owner': str(self.sheet), 'Resolved': str(source), 'Path': str(source), 'Handle': '1'}]
        self.fail_operation = 'embed-media'
        with self.assertRaisesRegex(RuntimeError, 'simulated failure'):
            self.run_job()
        self.assertNotIn('titleblock', self.calls)
        self.assertFalse((self.root / 'Cleaned CAD').exists())

    def test_mapped_drive_aliases_normalize_the_entire_graph(self):
        stamp = self.root / 'stamp.dwg'
        stamp.write_bytes(b'stamp')
        asset = self.root / 'logo.png'
        asset.write_bytes(b'asset')
        aliases = {'P:/stamp.dwg': stamp, 'P:/sheet.dwg': self.sheet, 'P:/logo.png': asset}
        resolve = Path.resolve
        def resolve_alias(path, *args, **kwargs):
            if path.as_posix() in aliases:
                return aliases[path.as_posix()]
            return resolve(path, *args, **kwargs)
        reference = {'Owner': 'P:/sheet.dwg', 'Name': 'Stamp', 'Path': 'P:/stamp.dwg', 'Resolved': 'P:/stamp.dwg'}
        scan = {'files': [str(self.sheet), 'P:/sheet.dwg', 'P:/stamp.dwg', str(stamp)],
                'references': [reference, dict(reference, Owner=str(self.sheet), Resolved=str(stamp))],
                'images': [{'Owner': 'P:/sheet.dwg', 'Handle': 'AB', 'Path': 'P:/logo.png', 'Resolved': 'P:/logo.png'}],
                'titleblocks': ['P:/stamp.dwg']}
        with patch.object(Path, 'resolve', resolve_alias):
            normalized = clean._canonicalize_scan(scan)
        self.assertEqual([str(self.sheet), str(stamp)], normalized['files'])
        self.assertEqual([dict(reference, Owner=str(self.sheet), Resolved=str(stamp))], normalized['references'])
        self.assertEqual(str(self.sheet), normalized['images'][0]['Owner'])
        self.assertEqual(str(asset), normalized['images'][0]['Resolved'])
        self.assertEqual('P:/logo.png', normalized['images'][0]['Path'])
        self.assertEqual([str(stamp)], normalized['titleblocks'])

    def run_job(self, worker=None):
        with patch.object(clean.tempfile, 'mkdtemp', return_value=str(self.work)):
            return clean.run(self.root, self.selection, 'unused', worker=worker or self.worker, dll='test.dll')

    def test_delivery_preserves_originals_and_relative_structure(self):
        result = self.run_job()
        output = Path(result['output'])
        self.assertEqual(b'titleblock original', self.tb.read_bytes())
        self.assertEqual(b'sheet original', self.sheet.read_bytes())
        self.assertEqual(b'cleaned', (output / 'Xrefs' / 'x-TB.dwg').read_bytes())
        self.assertEqual(b'cleaned', (output / 'Electrical' / 'E01.dwg').read_bytes())
        self.assertTrue((output / 'cleanup-report.json').is_file())
        self.assertEqual(2, self.calls.count('verify'))
        self.assertFalse(self.work.exists())

    def test_media_stops_before_prepare_and_delivery(self):
        self.media = ['logo RasterImage']
        with self.assertRaisesRegex(RuntimeError, 'embedding is not supported'):
            self.run_job()
        self.assertEqual(['validate-titleblock', 'scan'], self.calls)
        self.assertFalse((self.root / 'Cleaned CAD').exists())
        self.assertTrue(self.work.exists())

    def test_temp_cleanup_failure_does_not_mark_delivered_drawings_failed(self):
        with patch.object(clean.shutil, 'rmtree', side_effect=PermissionError('locked temp file')):
            result = self.run_job()
        self.assertEqual('success', result['status'])
        self.assertTrue(Path(result['output']).is_dir())
        self.assertIn('could not be removed', result['cleanupWarning'])

    def test_wrong_titleblock_stops_before_scan_or_media_work(self):
        self.fail_operation = 'validate-titleblock'
        with self.assertRaisesRegex(RuntimeError, 'simulated failure'):
            self.run_job()
        self.assertEqual(['validate-titleblock'], self.calls)
        self.assertFalse((self.root / 'Cleaned CAD').exists())

    def test_titleblock_recommendation_requires_unique_name_and_paper_reference(self):
        site = 'Xrefs/San Mateo HS Site Xref (E).dwg'
        border = 'Xrefs/X-SMHS-AQ_TB-30x42-DSA.dwg'
        unused = 'Xrefs/Danny_Stringer_X-SMHS-AQ_TB-30x42-DSA.dwg'
        preview = {'titleblocks': [site, unused, border], 'detectedTitleblocks': [site, border]}
        clean._rank_titleblocks(preview)
        self.assertEqual(border, preview['recommendedTitleblock'])
        self.assertEqual(border, preview['titleblocks'][0])
        preview['detectedTitleblocks'].append(unused)
        clean._rank_titleblocks(preview)
        self.assertIsNone(preview['recommendedTitleblock'])

    def test_sheet_failure_never_delivers_partial_titleblock(self):
        self.fail_operation = 'sheet'
        with self.assertRaisesRegex(RuntimeError, 'simulated failure'):
            self.run_job()
        self.assertFalse((self.root / 'Cleaned CAD').exists())
        self.assertEqual(b'titleblock original', self.tb.read_bytes())

    def test_reopen_count_mismatch_blocks_delivery(self):
        def worker(*args):
            result = self.worker(*args)
            if args[3]['Operation'] == 'verify':
                result['modelEntities'] = 0
            return result
        with self.assertRaisesRegex(RuntimeError, 'counts changed'):
            self.run_job(worker)
        self.assertFalse((self.root / 'Cleaned CAD').exists())

    def test_source_edit_during_processing_blocks_delivery(self):
        def worker(*args):
            result = self.worker(*args)
            if args[3]['Operation'] == 'sheet':
                self.sheet.write_bytes(b'user edit')
            return result
        with self.assertRaisesRegex(RuntimeError, 'Source changed'):
            self.run_job(worker)
        self.assertEqual(b'user edit', self.sheet.read_bytes())
        self.assertFalse((self.root / 'Cleaned CAD').exists())

    def test_path_escape_and_nonfinite_dimensions_rejected(self):
        outside = self.root.parent / 'outside.dwg'
        outside.write_bytes(b'outside')
        self.selection['titleblock'] = '../outside.dwg'
        with self.assertRaisesRegex(RuntimeError, 'inside the project'):
            self.run_job()
        self.selection['titleblock'] = 'Xrefs/x-TB.dwg'
        self.selection['width'] = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'valid sheet dimensions'):
            self.run_job()
        self.assertEqual([], self.calls)

    def test_pdf_orientation_and_mixed_page_sizes(self):
        folder = self.root / 'Electrical' / 'Checkset'
        folder.mkdir()
        with fitz.open() as doc:
            doc.new_page(width=612, height=792)  # Ignore administrative cover.
            doc.new_page(width=36 * 72, height=24 * 72)
            doc.new_page(width=24 * 72, height=36 * 72)
            doc.save(folder / 'set.pdf')
        result = clean.discover(self.root)
        self.assertEqual([(36, 24, 2), (24, 36, 3)],
                         [(s['width'], s['height'], s['page']) for s in result['sizes']])
        self.assertEqual([str(Path('Electrical/E01.dwg'))], result['drawings'])

    def test_worker_reports_progress_while_waiting(self):
        process = Mock()
        process.wait.side_effect = [clean.subprocess.TimeoutExpired('acad', 5), 0]
        def launch(*args, **kwargs):
            request = json.loads(Path(kwargs['env']['ACIES_CLEAN_JOB']).read_text())
            Path(request['ResultPath']).write_text(json.dumps({'success': True, 'details': {}}))
            return process
        messages = []
        with patch.object(clean.subprocess, 'Popen', side_effect=launch):
            clean.run_worker('acad', 'test.dll', self.tb, {'Operation': 'scan'}, self.work, notify=messages.append)
        self.assertTrue(any('reference inspection: running' in message for message in messages))
        process.kill.assert_not_called()

    def test_worker_timeout_still_terminates_process(self):
        process = Mock()
        with patch.object(clean.subprocess, 'Popen', return_value=process), \
                patch.object(clean.time, 'monotonic', side_effect=[0, 301]):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                clean.run_worker('acad', 'test.dll', self.tb, {'Operation': 'scan'}, self.work)
        process.kill.assert_called_once()


if __name__ == '__main__':
    unittest.main()
