import os
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _ensure_optional_dependency_stubs():
    try:
        from google import genai as _genai  # noqa: F401
        from google.genai import types as _types  # noqa: F401
    except Exception:
        google_module = sys.modules.get("google")
        if google_module is None:
            google_module = types.ModuleType("google")
            google_module.__path__ = []
            sys.modules["google"] = google_module
        genai_module = types.ModuleType("google.genai")
        genai_types_module = types.ModuleType("google.genai.types")
        genai_module.types = genai_types_module
        google_module.genai = genai_module
        sys.modules["google.genai"] = genai_module
        sys.modules["google.genai.types"] = genai_types_module

    try:
        import webview  # noqa: F401
    except Exception:
        webview_module = types.ModuleType("webview")
        webview_module.windows = []
        webview_module.create_window = lambda *args, **kwargs: None
        webview_module.start = lambda *args, **kwargs: None
        sys.modules["webview"] = webview_module

    try:
        from dotenv import load_dotenv as _load_dotenv  # noqa: F401
    except Exception:
        dotenv_module = types.ModuleType("dotenv")
        dotenv_module.load_dotenv = lambda *args, **kwargs: False
        sys.modules["dotenv"] = dotenv_module


_ensure_optional_dependency_stubs()

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from main import Api

SCRIPT_JS_PATH = REPO_ROOT / "script.js"
STYLES_CSS_PATH = REPO_ROOT / "styles.css"


def _make_pdf(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    file_path = folder / name
    file_path.write_bytes(b"%PDF-1.4\n")
    return file_path


class DeliverableQuickAccessPdfBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="acies-quick-access-pdf-")
        self.addCleanup(self._temp_dir.cleanup)
        self.project_root = Path(self._temp_dir.name) / "260243 Sample Clinic"
        self.pdf_root = self.project_root / "PDF"

    def _project(self):
        return {
            "path": str(self.project_root),
            "localProjectPath": "",
            "id": "260243",
            "name": "Sample Clinic",
        }

    def test_opens_newest_issue_folder_pdf_for_active_discipline(self):
        _make_pdf(
            self.pdf_root / "2026.05.02 MEP DD90",
            "260243 Sample Clinic Electrical.pdf",
        )
        newest = _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Plumbing.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(self._project(), "Electrical", "")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(newest), result["path"])
        self.assertEqual("2026.08.16 MEP IFP", result["folderName"])
        self.assertEqual("2026-08-16", result["issuedOn"])

    def test_discipline_selects_the_matching_file_in_the_folder(self):
        folder = self.pdf_root / "2026.08.16 MEP IFP"
        _make_pdf(folder, "260243 Sample Clinic Electrical.pdf")
        mechanical = _make_pdf(folder, "260243 Sample Clinic Mechanical.pdf")

        result = self.api.find_latest_deliverable_pdf(self._project(), "Mechanical", "")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(mechanical), result["path"])
        self.assertEqual("Mechanical", result["discipline"])

    def test_matching_deliverable_folder_beats_a_newer_unrelated_issue(self):
        ifp = _make_pdf(
            self.pdf_root / "2026.05.02 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFC",
            "260243 Sample Clinic Electrical.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(
            self._project(), "Electrical", "IFP")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(ifp), result["path"])
        self.assertTrue(result["matchedDeliverable"])

    def test_numbered_deliverable_matches_zero_padded_folder(self):
        expected = _make_pdf(
            self.pdf_root / "2026.03.04 RFI 03",
            "260243 Sample Clinic Electrical.pdf",
        )
        _make_pdf(
            self.pdf_root / "2026.07.01 RFI 07",
            "260243 Sample Clinic Electrical.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(
            self._project(), "Electrical", "RFI #3")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_falls_back_to_an_older_issue_when_the_newest_skipped_the_discipline(self):
        expected = _make_pdf(
            self.pdf_root / "2026.05.02 MEP DD90",
            "260243 Sample Clinic Plumbing.pdf",
        )
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(self._project(), "Plumbing", "")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_local_project_copy_is_used_when_the_server_path_is_missing(self):
        local_root = Path(self._temp_dir.name) / "Local Projects" / "260243 Sample Clinic"
        expected = _make_pdf(
            local_root / "PDF" / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        project = self._project()
        project["path"] = str(self.project_root)  # never created on disk
        project["localProjectPath"] = str(local_root)

        result = self.api.find_latest_deliverable_pdf(project, "Electrical", "")

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_missing_pdf_folder_reports_an_actionable_error(self):
        self.project_root.mkdir(parents=True, exist_ok=True)

        result = self.api.find_latest_deliverable_pdf(self._project(), "Electrical", "")

        self.assertEqual("error", result["status"])
        self.assertIn("PDF folder", result["message"])

    def test_missing_discipline_pdf_reports_an_actionable_error(self):
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        result = self.api.find_latest_deliverable_pdf(self._project(), "Plumbing", "")

        self.assertEqual("error", result["status"])
        self.assertIn("Plumbing", result["message"])

    def test_unknown_discipline_is_rejected_before_touching_disk(self):
        result = self.api.find_latest_deliverable_pdf(self._project(), "General", "")

        self.assertEqual("error", result["status"])
        self.assertIn("Electrical", result["message"])

    def test_open_latest_deliverable_pdf_opens_the_resolved_file(self):
        expected = _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        with patch.object(self.api, "open_path", return_value={"status": "success"}) as opener:
            result = self.api.open_latest_deliverable_pdf(
                self._project(), "Electrical", "IFP")

        self.assertEqual("success", result["status"])
        opener.assert_called_once_with(str(expected))

    def test_open_latest_deliverable_pdf_surfaces_open_failures(self):
        _make_pdf(
            self.pdf_root / "2026.08.16 MEP IFP",
            "260243 Sample Clinic Electrical.pdf",
        )

        with patch.object(
            self.api, "open_path", return_value={"status": "error", "message": "boom"}
        ):
            result = self.api.open_latest_deliverable_pdf(
                self._project(), "Electrical", "IFP")

        self.assertEqual("error", result["status"])
        self.assertEqual("boom", result["message"])


class ArchSetQuickAccessBackendTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        key_patch = patch.object(self.api, '_resolve_panel_schedule_api_key', return_value='')
        self.key_resolver = key_patch.start()
        self.addCleanup(key_patch.stop)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="acies-quick-access-arch-")
        self.addCleanup(self._temp_dir.cleanup)
        self.project_root = Path(self._temp_dir.name) / "260243 Sample Clinic"
        self.arch_root = self.project_root / "Arch"

    def _project(self):
        return {
            "path": str(self.project_root),
            "localProjectPath": "",
            "id": "260243",
            "name": "Sample Clinic",
        }

    def test_dated_file_name_wins_over_an_older_dated_set(self):
        _make_pdf(self.arch_root, "Sample Clinic ARCH 2026-05-02.pdf")
        newest = _make_pdf(self.arch_root, "Sample Clinic ARCH 2026-08-16.pdf")

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(newest), result["path"])
        self.assertEqual("2026-08-16", result["issuedOn"])

    def test_dated_subfolder_supplies_the_date_when_the_file_has_none(self):
        _make_pdf(self.arch_root / "2026.05.02 ARCH DD", "A-Set.pdf")
        newest = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(newest), result["path"])
        self.assertEqual("2026-08-16", result["issuedOn"])
        self.assertEqual("2026.08.16 ARCH IFP", result["folderName"])

    def test_dated_set_beats_an_undated_one_regardless_of_mtime(self):
        dated = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")
        undated = _make_pdf(self.arch_root / "Plans", "A-100 Floor Plan.pdf")
        os.utime(undated, (2_000_000_000, 2_000_000_000))
        os.utime(dated, (1_000_000_000, 1_000_000_000))

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(dated), result["path"])

    def test_undated_sets_fall_back_to_the_newest_file(self):
        older = _make_pdf(self.arch_root / "Plans", "A-100 Floor Plan.pdf")
        newer = _make_pdf(self.arch_root / "Plans", "A-200 Reflected Ceiling.pdf")
        os.utime(older, (1_000_000_000, 1_000_000_000))
        os.utime(newer, (2_000_000_000, 2_000_000_000))

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(newer), result["path"])
        self.assertEqual("", result["issuedOn"])

    def test_archived_subtrees_are_skipped(self):
        _make_pdf(self.arch_root / "Archive" / "2026.09.01 ARCH", "A-Set.pdf")
        expected = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_non_pdf_files_are_ignored(self):
        (self.arch_root / "Plans").mkdir(parents=True, exist_ok=True)
        (self.arch_root / "Plans" / "A-100.dwg").write_bytes(b"dwg")
        (self.arch_root / "Plans" / "backgrounds.zip").write_bytes(b"zip")

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("error", result["status"])
        self.assertIn("No PDF", result["message"])

    def test_project_id_ancestor_resolves_the_sibling_arch_folder(self):
        expected = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")
        electrical = self.project_root / "Electrical"
        electrical.mkdir(parents=True, exist_ok=True)

        project = self._project()
        project["path"] = str(electrical)

        result = self.api.find_latest_arch_set(project)

        self.assertEqual("success", result["status"])
        self.assertEqual(str(expected), result["path"])

    def test_missing_arch_folder_reports_an_actionable_error(self):
        self.project_root.mkdir(parents=True, exist_ok=True)

        result = self.api.find_latest_arch_set(self._project())

        self.assertEqual("error", result["status"])
        self.assertIn("Arch folder", result["message"])

    def test_open_latest_arch_set_opens_the_resolved_file(self):
        expected = _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")

        with patch.object(self.api, "open_path", return_value={"status": "success"}) as opener:
            result = self.api.open_latest_arch_set(self._project())

        self.assertEqual("success", result["status"])
        opener.assert_called_once_with(str(expected))

    def test_open_latest_arch_set_surfaces_open_failures(self):
        _make_pdf(self.arch_root / "2026.08.16 ARCH IFP", "A-Set.pdf")

        with patch.object(
            self.api, "open_path", return_value={"status": "error", "message": "boom"}
        ):
            result = self.api.open_latest_arch_set(self._project())

        self.assertEqual("error", result["status"])
        self.assertEqual("boom", result["message"])

    def _decision_response(self, choice='pdf_000001', confidence=0.95):
        response = MagicMock()
        response.__enter__.return_value = response
        response.json.return_value = {'answers': {'latest_arch_set': {
            'type': 'choice', 'choice': choice, 'confidence': confidence,
        }}}
        return response

    def _make_decision_candidates(self):
        _make_pdf(self.arch_root / '2026.11.12 Specifications', 'Project Specs.pdf')
        _make_pdf(self.arch_root / '2026.11.11 Received', 'Combined Drawing Set.pdf')
        return _make_pdf(self.arch_root / 'Received 11-10-2026' / 'Permit', 'Full Architectural Set.pdf')

    def test_decision_can_choose_a_full_set_over_newer_specs_using_metadata(self):
        expected = self._make_decision_candidates()
        self.key_resolver.return_value = 'test-key'
        with patch('main.requests.post', return_value=self._decision_response()) as post:
            result = self.api.find_latest_arch_set(self._project())

        self.assertEqual(str(expected), result['path'])
        self.assertEqual('decision', result['selectionMethod'])
        args, kwargs = post.call_args
        self.assertEqual('https://generativelanguage.googleapis.com/v1beta/decisions', args[0])
        self.assertEqual('test-key', kwargs['headers']['x-goog-api-key'])
        self.assertEqual((3, 10), kwargs['timeout'])
        self.assertFalse(kwargs['allow_redirects'])
        payload = kwargs['json']
        self.assertEqual('gemini-decision-1', payload['model'])
        criteria = payload['questions']['latest_arch_set']['criteria']
        metadata = json.loads(criteria['pdf_000001'])
        self.assertEqual('Full Architectural Set.pdf', metadata['fileName'])
        self.assertEqual(os.path.join('Received 11-10-2026', 'Permit'), metadata['parentFolder'])
        self.assertIn('modifiedAt', metadata)
        self.assertIn('sizeBytes', metadata)
        self.assertNotIn(str(self.project_root), json.dumps(payload))
        self.assertNotIn('%PDF', json.dumps(payload))
        self.assertIn('unsuitable', criteria)

    def test_no_key_compares_architectural_scope_before_dates_without_network(self):
        expected = self._make_decision_candidates()
        with patch('main.requests.post') as post:
            result = self.api.find_latest_arch_set(self._project())
        post.assert_not_called()
        self.assertEqual('scope_and_dates', result['selectionMethod'])
        self.assertEqual('no_api_key', result['selectionReason'])
        self.assertEqual(str(expected), result['path'])

    def test_single_candidate_needs_no_network_or_key(self):
        expected = _make_pdf(self.arch_root, 'Architectural.pdf')
        with patch('main.requests.post') as post:
            result = self.api.find_latest_arch_set(self._project())
        post.assert_not_called()
        self.key_resolver.assert_not_called()
        self.assertEqual(str(expected), result['path'])
        self.assertEqual('single_candidate', result['selectionReason'])

    def test_uncertain_invalid_and_unsuitable_answers_use_dates(self):
        expected = self._make_decision_candidates()
        self.key_resolver.return_value = 'test-key'
        for choice, confidence in [
            ('pdf_000001', 0.6), ('unsuitable', 0.99),
            ('C:/invented.pdf', 0.99), ('pdf_000001', float('nan')),
            ('pdf_000001', 1.5), ('pdf_000001', True), ('pdf_000001', '0.95'),
        ]:
            with self.subTest(choice=choice, confidence=confidence):
                with patch('main.requests.post', return_value=self._decision_response(choice, confidence)):
                    result = self.api.find_latest_arch_set(self._project())
                self.assertEqual('scope_and_dates', result['selectionMethod'])
                self.assertEqual(str(expected), result['path'])

    def test_network_quota_and_bad_response_failures_preserve_local_open(self):
        self._make_decision_candidates()
        self.key_resolver.return_value = 'test-key'
        for error in (TimeoutError('timeout'), RuntimeError('429 quota'), KeyError('answers')):
            with self.subTest(error=error):
                with patch('main.requests.post', side_effect=error) as post, patch.object(
                    self.api, 'open_path', return_value={'status': 'success'}
                ) as opener:
                    result = self.api.open_latest_arch_set(self._project())
                self.assertEqual('success', result['status'])
                self.assertEqual('unavailable', result['selectionReason'])
                opener.assert_called_once_with(result['path'])
                post.assert_called_once()

    def test_unchanged_inventory_is_cached_and_changes_invalidate_it(self):
        expected = self._make_decision_candidates()
        self.key_resolver.return_value = 'test-key'
        with patch('main.requests.post', return_value=self._decision_response()) as post:
            self.api.find_latest_arch_set(self._project())
            self.api.find_latest_arch_set(self._project())
            self.assertEqual(1, post.call_count)
            expected.write_bytes(b'%PDF-1.4\nupdated')
            self.api.find_latest_arch_set(self._project())
            self.assertEqual(2, post.call_count)
            expected.rename(expected.with_name('Renamed Architectural Set.pdf'))
            self.api.find_latest_arch_set(self._project())
            self.assertEqual(3, post.call_count)

    def test_large_inventory_compares_every_candidate_then_batch_winners(self):
        self.key_resolver.return_value = 'test-key'
        entries = [{
            'path': str(self.arch_root / f'Set-{i}.pdf'),
            'fileName': f'Set-{i}.pdf', 'parentFolder': '.', 'issuedOn': '',
            'modifiedAt': '2026-11-12T00:00:00+00:00', 'modifiedNs': i, 'sizeBytes': 10,
        } for i in range(260)]
        responses = [self._decision_response(choice) for choice in (
            'pdf_000100', 'pdf_000259', 'pdf_000259',
        )]
        with patch('main.requests.post', side_effect=responses) as post:
            selected, reason = self.api._select_arch_set_with_decision(entries, str(self.arch_root))
        self.assertIs(entries[259], selected)
        self.assertEqual('decision', reason)
        criteria = [call.kwargs['json']['questions']['latest_arch_set']['criteria']
                    for call in post.call_args_list]
        self.assertEqual([255, 7, 3], [len(options) for options in criteria])
        self.assertEqual(set(f'pdf_{i:06d}' for i in range(260)),
                         (set(criteria[0]) | set(criteria[1])) - {'unsuitable'})

    def test_removed_selection_is_not_opened(self):
        self._make_decision_candidates()
        missing = {'path': str(self.arch_root / 'removed.pdf')}
        with patch.object(self.api, '_select_arch_set_with_decision', return_value=(missing, 'decision')):
            with patch.object(self.api, 'open_path') as opener:
                result = self.api.open_latest_arch_set(self._project())
        self.assertEqual('error', result['status'])
        opener.assert_not_called()

    def _make_stamford_candidates(self):
        _make_pdf(self.arch_root / '2026-11-09 Furniture Dwg',
                  'CHARLES SCHWAB STAMFORD FURNITURE PLAN_091026.pdf')
        review = self.arch_root / '2026-07-09 CS 90% Comments' / 'Stamford,CT - 90% Redline Comments20260709123212'
        expected = _make_pdf(review, 'CS_Stamford CT_90% Set for review_07-02-2026 ARCH.pdf')
        _make_pdf(review, 'CS_Stamford CT_90% Set for review_07-02-2026 MEP.pdf')
        _make_pdf(self.arch_root / '2026-08-11 LL Comments', 'Schwab_MEP Peer Review Comments_081026.pdf')
        _make_pdf(self.arch_root / '2026-07-22 Heat Map', 'Stamford CT BRCTXX WAP.pdf')
        _make_pdf(self.arch_root / '2026-03-04 Initial Info', 'Earlier ARCH Set.pdf')
        return expected

    def test_stamford_63_percent_ai_choice_does_not_fall_back_to_furniture(self):
        expected = self._make_stamford_candidates()
        self.key_resolver.return_value = 'test-key'
        # The live API picked the correct ARCH set, but its actual 0.6376
        # confidence triggered the old newest-PDF fallback and opened furniture.
        response = self._decision_response('pdf_000000', 0.6375974259130904)
        with patch('main.requests.post', return_value=response) as post:
            result = self.api.find_latest_arch_set(self._project())
        self.assertEqual(str(expected), result['path'])
        self.assertEqual('scope_and_dates', result['selectionMethod'])
        self.assertEqual('uncertain', result['selectionReason'])
        criteria = post.call_args.kwargs['json']['questions']['latest_arch_set']['criteria']
        self.assertEqual(3, len(criteria))  # Two ARCH sets and the unsuitable option.
        self.assertNotIn('FURNITURE', json.dumps(criteria))

    def test_stamford_without_api_key_opens_arch_set(self):
        expected = self._make_stamford_candidates()
        with patch('main.requests.post') as post:
            result = self.api.find_latest_arch_set(self._project())
        post.assert_not_called()
        self.assertEqual(str(expected), result['path'])

    def test_stamford_api_failure_opens_arch_set(self):
        expected = self._make_stamford_candidates()
        self.key_resolver.return_value = 'test-key'
        with patch('main.requests.post', side_effect=TimeoutError):
            result = self.api.find_latest_arch_set(self._project())
        self.assertEqual(str(expected), result['path'])
        self.assertEqual('unavailable', result['selectionReason'])

    def test_furniture_only_folder_does_not_open_as_an_arch_set(self):
        _make_pdf(self.arch_root / '2026-11-09 Furniture Dwg', 'FURNITURE PLAN.pdf')
        with patch.object(self.api, 'open_path') as opener:
            result = self.api.open_latest_arch_set(self._project())
        self.assertEqual('error', result['status'])
        self.assertIn('No architectural drawing set', result['message'])
        opener.assert_not_called()

    def test_complete_arch_set_beats_newer_individual_architectural_sheet_offline(self):
        expected = _make_pdf(self.arch_root / '2026-07-09', 'Project_ARCH Set.pdf')
        _make_pdf(self.arch_root / '2026-11-09', 'Project_Architectural_A-101_Floor Plan.pdf')
        result = self.api.find_latest_arch_set(self._project())
        self.assertEqual(str(expected), result['path'])


class IssueDateParsingTests(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)

    def test_leading_stamp_is_read_from_issue_folder_names(self):
        parsed = self.api._parse_deliverable_pdf_issue_date("2026.08.16 MEP IFP")
        self.assertEqual("2026-08-16", parsed.isoformat())

    def test_impossible_dates_are_rejected(self):
        self.assertIsNone(self.api._parse_deliverable_pdf_issue_date("2026.13.40 MEP IFP"))

    def test_implausible_years_are_rejected(self):
        self.assertIsNone(self.api._search_issue_date("Set 1234-05-06"))

    def test_bare_project_numbers_are_not_read_as_dates(self):
        self.assertIsNone(self.api._search_issue_date("260243 Sample Clinic Arch"))

    def test_embedded_stamp_is_found_anywhere_in_a_name(self):
        parsed = self.api._search_issue_date("Sample Clinic ARCH 2026-08-16")
        self.assertEqual("2026-08-16", parsed.isoformat())


class DeliverableQuickAccessPdfUiTests(unittest.TestCase):
    def test_quick_access_dropdown_is_wired_into_the_card_action_row(self):
        text = SCRIPT_JS_PATH.read_text(encoding="utf-8")

        for expected in (
            "const DELIVERABLE_QUICK_ACCESS_ACTIONS = Object.freeze([",
            'id: "openLatestPdf"',
            "getLabel: () => `Open Latest ${getActiveWorkroomDiscipline()} Set`",
            'id: "openLatestArchSet"',
            'label: "Open Latest Arch Set"',
            "function getDeliverableQuickAccessActionLabel(action) {",
            "function createDeliverableQuickAccessDropdown(deliverable, project, card) {",
            "async function runDeliverableQuickAccessOpen({",
            "function openLatestDeliverablePdf(project, deliverable) {",
            "function openLatestArchSet(project) {",
            'methodName: "open_latest_deliverable_pdf"',
            'methodName: "open_latest_arch_set"',
            "const discipline = getActiveWorkroomDiscipline();",
            "quickAccessDropdown.classList.add(\"deliverable-card-quick-access-action\");",
            # Pin moved into the card's More menu in the 2026-09-05 UX pass.
            "leftActions.append(statusDropdown, toolDropdown, quickAccessDropdown);",
            'dropdown.classList.contains("deliverable-card-quick-access-action");',
        ):
            self.assertIn(expected, text)

    def test_quick_access_menu_has_styles(self):
        text = STYLES_CSS_PATH.read_text(encoding="utf-8")

        self.assertIn(".deliverable-quick-access-menu {", text)


if __name__ == "__main__":
    unittest.main()
