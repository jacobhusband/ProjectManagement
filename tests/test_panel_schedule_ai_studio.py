import json
import tempfile
import types
import unittest
from pathlib import Path

import openpyxl
import pymupdf
from PIL import Image

import panel_schedule_ai as psa


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "CircuitBreakerAI" / "ElectricalPanels" / "Template.xlsx"


def _make_sample_png(path: Path, size=(640, 480), color=(235, 240, 245)) -> Path:
    img = Image.new("RGB", size, color)
    img.save(path, format="PNG")
    return path


def _make_sample_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    # Page 1: Cover sheet (not a panel schedule)
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text((72, 100), "ELECTRICAL COVER SHEET E00.00")
    # Page 2..5: Panel schedules + other sheets (5 pages triggers smart panel-page selection)
    p2 = doc.new_page(width=612, height=792)
    p2.insert_text((72, 100), 'PANEL SCHEDULE (E) PANEL "D3"\nCKT# LOAD DESCRIPTION BUS RATING 100A')
    for i in range(3, 6):
        p = doc.new_page(width=612, height=792)
        p.insert_text((72, 100), f"LIGHTING PLAN SHEET E0{i}.00")
    doc.save(str(path))
    doc.close()
    return path


class PanelScheduleAiStudioTests(unittest.TestCase):
    def test_inspect_sources_handles_images_and_multipage_pdfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            img_path = _make_sample_png(tmp_dir / "panel_breakers.png")
            pdf_path = _make_sample_pdf(tmp_dir / "record_set.pdf")

            res = psa.inspect_sources(paths=[str(img_path), str(pdf_path)], temp_dir=tmp_dir)
            self.assertEqual(res["warnings"], [])
            # 1 image + 5 PDF pages
            self.assertEqual(len(res["items"]), 6)

            img_item = res["items"][0]
            self.assertEqual(img_item["kind"], "image")
            self.assertTrue(img_item["selected"])
            self.assertEqual(len(img_item["dhash"]), 16)
            self.assertTrue(img_item["thumbDataUrl"].startswith("data:image/jpeg;base64,"))
            self.assertTrue(img_item["viewerDataUrl"].startswith("data:image/jpeg;base64,"))

            pdf_items = res["items"][1:]
            self.assertEqual(len(pdf_items), 5)
            # Only page 2 looks like a panel schedule, so on a 5-page PDF it should be auto-selected.
            self.assertFalse(pdf_items[0]["selected"])
            self.assertTrue(pdf_items[1]["selected"])
            self.assertTrue(pdf_items[1]["looksLikePanel"])

            rendered = psa.render_source_viewer_image(pdf_items[1])
            self.assertTrue(rendered.startswith("data:image/jpeg;base64,"))

    def test_nec_load_calculation_matches_panel_d3_csv(self):
        # Directly replicates Jacob's real Panel D3 schedule values.
        panel = psa.normalize_extracted_panel(
            {
                "panel_name": "D3",
                "voltage": "120/208V",
                "bus_rating": "100A",
                "main_type": "MLO",
                "phase": "3",
                "wire": "4",
                "fed_from": "PANEL 'D2'",
                "circuits": [
                    {"circuit_number": 1, "description": "PRIVATE OFFICE 241", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.9"]},
                    {"circuit_number": 2, "description": "218 SYS. FURNITURE", "breaker_amps": "20", "poles": 1, "load_type": "D", "note": "1", "phase_kva": ["1.1"]},
                    {"circuit_number": 3, "description": "PRIVATE OFFICE 242", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.9"]},
                    {"circuit_number": 4, "description": "PRINTER", "breaker_amps": "20", "poles": 1, "load_type": "D", "note": "1", "phase_kva": ["0.3"]},
                    {"circuit_number": 5, "description": "PRIVATE OFFICE 243", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.9"]},
                    {"circuit_number": 6, "description": "PRINTER", "breaker_amps": "20", "poles": 1, "load_type": "D", "note": "1", "phase_kva": ["0.3"]},
                    {"circuit_number": 7, "description": "OPEN OFFICE 246", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.72"]},
                    {"circuit_number": 8, "description": "IT CLOSET REC", "breaker_amps": "20", "poles": 1, "load_type": "D", "note": "2", "phase_kva": ["0.18"]},
                    {"circuit_number": 9, "description": "OPEN OFFICE 246", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.72"]},
                    {"circuit_number": 10, "description": "SONITROL", "breaker_amps": "20", "poles": 1, "load_type": "D", "note": "2", "phase_kva": ["0.5"]},
                    {"circuit_number": 11, "description": "OPEN OFFICE 246", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.72"]},
                    {"circuit_number": 12, "description": "EXTERIOR GROUND LIGHTS", "breaker_amps": "20", "poles": 1, "load_type": "C", "note": "1", "phase_kva": ["1.9"]},
                    {"circuit_number": 13, "description": "OPEN OFFICE 246", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.72"]},
                    {"circuit_number": 14, "description": "EXTERIOR WALKWAY LIGHTS", "breaker_amps": "20", "poles": 1, "load_type": "C", "note": "1", "phase_kva": ["1.6"]},
                    {"circuit_number": 15, "description": "HALL 244 - CONV RECEPS", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.72"]},
                    {"circuit_number": 16, "description": "EXTERIOR POLE LIGHTS", "breaker_amps": "20", "poles": 1, "load_type": "C", "note": "1", "phase_kva": ["1.6"]},
                    {"circuit_number": 17, "description": "LOCKING RECEPTACLE", "breaker_amps": "30", "poles": 1, "load_type": "D", "note": "3", "phase_kva": ["3.6"]},
                    {"circuit_number": 18, "description": "SPARE", "breaker_amps": "20", "poles": 1, "load_type": "", "note": "1", "phase_kva": []},
                    {"circuit_number": 19, "description": "LOCKING RECEPTACLE", "breaker_amps": "30", "poles": 1, "load_type": "D", "note": "3", "phase_kva": ["1.92"]},
                    {"circuit_number": 20, "description": "SPARE", "breaker_amps": "20", "poles": 1, "load_type": "", "note": "1", "phase_kva": []},
                    {"circuit_number": 21, "description": "PRIVATE OFFICE 245", "breaker_amps": "20", "poles": 1, "load_type": "G", "note": "2", "phase_kva": ["0.9"]},
                    {"circuit_number": 22, "description": "2ND FLOOR TV", "breaker_amps": "20", "poles": 1, "load_type": "C", "note": "1", "phase_kva": ["0.5"]},
                    {"circuit_number": 23, "description": "SPARE", "breaker_amps": "20", "poles": 1, "load_type": "", "note": "1", "phase_kva": []},
                    {"circuit_number": 24, "description": "2ND FLOOR TV", "breaker_amps": "20", "poles": 1, "load_type": "C", "note": "1", "phase_kva": ["0.5"]},
                ],
            }
        )
        summary = panel["summary"]
        self.assertEqual(summary["phaseA"], 7.14)
        self.assertEqual(summary["phaseB"], 6.14)
        self.assertEqual(summary["phaseC"], 7.92)
        self.assertEqual(summary["connectedTotalKva"], 21.2)
        self.assertEqual(summary["demandTotalKva"], 22.73)
        self.assertEqual(summary["demandAmps"], 63.1)
        self.assertEqual(panel["fedFrom"], "FED FROM PANEL 'D2'")

    def test_analyze_sources_uses_gemini_4_hydrogen_and_retries_429(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            img_path = _make_sample_png(tmp_dir / "asbuilt.png")
            inspected = psa.inspect_sources(paths=[str(img_path)], temp_dir=tmp_dir)
            sources = inspected["items"]

            calls = []
            sleeps = []

            batch_payload = psa.ExtractedPanelBatchSchema(
                overall_notes="Extracted 2 panels from as-built sheet.",
                panels=[
                    psa.ExtractedPanelSchema(
                        panel_name="(E) PANEL 'D2'",
                        source_kind="as_built_drawing",
                        source_indices=[0],
                        voltage="120/208V",
                        bus_rating="400",
                        main_type="MLO",
                        phase="3",
                        wire="4",
                        mounting="SURFACE",
                        enclosure="NEMA 1",
                        aic_rating="EXISTING",
                        condition="EXISTING",
                        fed_from="PANEL 'D1'",
                        circuits=[
                            psa.ExtractedCircuitSchema(
                                circuit_number=1,
                                description="LTG - OPEN OFFICE",
                                breaker_amps="20",
                                poles=1,
                                load_type="C",
                                note="1",
                                phase_kva=["1000 VA"],
                                confidence="high",
                            ),
                            psa.ExtractedCircuitSchema(
                                circuit_number=3,
                                description='"',
                                breaker_amps="20",
                                poles=1,
                                load_type="C",
                                note="1",
                                phase_kva=["1.1"],
                                confidence="medium",
                                review_note="Slight blur on label",
                            ),
                            psa.ExtractedCircuitSchema(
                                circuit_number=35,
                                description="PANEL 'D3'",
                                breaker_amps="80",
                                poles=3,
                                load_type="D",
                                note="1",
                                phase_kva=["7.92", "7.14", "6.14"],
                                confidence="high",
                            ),
                        ],
                    )
                ],
            )

            class FakeModels:
                def generate_content(self, **kwargs):
                    calls.append(kwargs["model"])
                    if len(calls) == 1:
                        raise RuntimeError("429 RESOURCE_EXHAUSTED: retry in 2s")
                    return types.SimpleNamespace(parsed=batch_payload, text="")

            fake_client = types.SimpleNamespace(models=FakeModels())

            result = psa.analyze_sources_with_hydrogen(
                sources=sources,
                api_key="test-key",
                mode="as_built_drawing",
                client_factory=lambda _key: fake_client,
                sleep_fn=lambda sec: sleeps.append(sec),
            )

            self.assertEqual(calls, ["gemini-4-hydrogen", "gemini-4-hydrogen"])
            self.assertEqual(sleeps, [2.0])
            self.assertEqual(result["model"], "gemini-4-hydrogen")
            self.assertEqual(len(result["panels"]), 1)

            panel = result["panels"][0]
            self.assertEqual(panel["panelName"], "D2")
            self.assertEqual(panel["busRating"], "400A")
            # VA converted to kVA and ditto mark resolved
            c1 = next(c for c in panel["circuits"] if c["circuitNumber"] == 1)
            c3 = next(c for c in panel["circuits"] if c["circuitNumber"] == 3)
            self.assertEqual(c1["phaseKva"], [1.0])
            self.assertEqual(c3["description"], "LTG - OPEN OFFICE")
            self.assertEqual(c3["confidence"], "medium")
            self.assertEqual(panel["summary"]["flaggedCount"], 1)

    def test_apply_estimated_kva_preserves_extracted_values(self):
        panel = psa.normalize_extracted_panel(
            {
                "panel_name": "LP1",
                "voltage": "120/208V",
                "bus_rating": "225A",
                "circuits": [
                    {"circuit_number": 1, "description": "PRIVATE OFFICE 101", "breaker_amps": "20", "poles": 1, "load_type": "G", "phase_kva": ["1.45"]},
                    {"circuit_number": 3, "description": "OPEN OFFICE 102", "breaker_amps": "20", "poles": 1, "load_type": "G", "phase_kva": []},
                    {"circuit_number": 5, "description": "SPARE", "breaker_amps": "20", "poles": 1, "load_type": "", "phase_kva": []},
                ],
            }
        )
        updated = psa.apply_estimated_kva_to_panel(panel, overwrite_existing=False)
        c1 = next(c for c in updated["circuits"] if c["circuitNumber"] == 1)
        c3 = next(c for c in updated["circuits"] if c["circuitNumber"] == 3)
        c5 = next(c for c in updated["circuits"] if c["circuitNumber"] == 5)
        # Existing extracted value untouched
        self.assertEqual(c1["phaseKva"], [1.45])
        self.assertFalse(c1["kvaEstimated"])
        # Blank active circuit filled deterministically
        self.assertEqual(c3["phaseKva"], [0.72])
        self.assertTrue(c3["kvaEstimated"])
        # Spare remains empty
        self.assertEqual(c5["phaseKva"], [])

    def test_export_new_and_append_excel_preserves_template_formulas(self):
        self.assertTrue(TEMPLATE_PATH.exists(), "Template.xlsx must exist")
        with tempfile.TemporaryDirectory() as tmp:
            out_xlsx = Path(tmp) / "260999 Panels.xlsx"
            panel_d2 = psa.normalize_extracted_panel(
                {
                    "panel_name": "D2",
                    "voltage": "120/208V",
                    "bus_rating": "400A",
                    "main_type": "MLO",
                    "phase": "3",
                    "wire": "4",
                    "mounting": "SURFACE",
                    "enclosure": "NEMA 1",
                    "aic_rating": "EXISTING",
                    "condition": "EXISTING",
                    "fed_from": "FED FROM PANEL 'D1'",
                    "circuits": [
                        {"circuit_number": 1, "description": "LTG - OPEN OFFICE", "breaker_amps": "20", "poles": 1, "load_type": "C", "note": "2", "phase_kva": ["1.0"]},
                        {"circuit_number": 35, "description": "PANEL 'D3'", "breaker_amps": "80", "poles": 3, "load_type": "D", "note": "1", "phase_kva": ["7.92", "7.14", "6.14"]},
                        {"circuit_number": 36, "description": "WATER HEATER", "breaker_amps": "30", "poles": 2, "load_type": "C", "note": "1", "phase_kva": ["2.3", "2.3"]},
                    ],
                }
            )
            panel_hv = psa.normalize_extracted_panel(
                {
                    "panel_name": "H1",
                    "voltage": "277/480V",
                    "bus_rating": "225A",
                    "main_type": "MCB",
                    "main_breaker_amps": "200A",
                    "phase": "3",
                    "wire": "4",
                    "condition": "NEW",
                    "fed_from": "FED FROM MSB",
                    "circuits": [
                        {"circuit_number": 1, "description": "HIGH BAY LIGHTING", "breaker_amps": "20", "poles": 1, "load_type": "C", "note": "3", "phase_kva": ["2.4"]},
                    ],
                }
            )

            res = psa.export_panels_to_excel(
                [panel_d2, panel_hv],
                str(out_xlsx),
                TEMPLATE_PATH,
                mode="new",
            )
            self.assertEqual(res["sheets"], ["D2", "H1"])
            self.assertTrue(out_xlsx.exists())

            wb = openpyxl.load_workbook(out_xlsx, data_only=False)
            try:
                # Only exported panels + TEMPLATE (example sheets HPT/Ax/Bx pruned!)
                self.assertEqual(wb.sheetnames, ["D2", "H1", "TEMPLATE"])

                ws_d2 = wb["D2"]
                self.assertEqual(ws_d2["A3"].value.strip(), '(E) PANEL "D2"')
                self.assertEqual(ws_d2["G2"].value, "120/208V")
                self.assertEqual(ws_d2["G3"].value, "400A")
                self.assertEqual(ws_d2["K2"].value, 4)
                self.assertEqual(ws_d2["K3"].value, 3)
                self.assertEqual(ws_d2["P3"].value, "FED FROM PANEL 'D1'")
                self.assertIn(ws_d2["P4"].value, (None, ""))
                # 3-pole breaker at Ckt 35 (Row 25, 26, 27)
                self.assertEqual(ws_d2["F25"].value, "PANEL 'D3'")
                self.assertEqual(ws_d2["D25"].value, 3)
                self.assertEqual(ws_d2["E25"].value, 80)
                self.assertEqual(ws_d2["I25"].value, 7.92)
                self.assertEqual(ws_d2["F26"].value, "---")
                self.assertEqual(ws_d2["D26"].value, "-")
                self.assertEqual(ws_d2["I26"].value, 7.14)
                self.assertEqual(ws_d2["I27"].value, 6.14)
                # 2-pole breaker at Ckt 36 (Row 25, 26)
                self.assertEqual(ws_d2["L25"].value, "WATER HEATER")
                self.assertEqual(ws_d2["O25"].value, 2)
                self.assertEqual(ws_d2["P25"].value, 30)
                self.assertEqual(ws_d2["K25"].value, 2.3)
                self.assertEqual(ws_d2["L26"].value, "---")
                self.assertEqual(ws_d2["K26"].value, 2.3)
                # Formulas preserved + voltage-aware Q38
                self.assertIn("SUMIF", str(ws_d2["F30"].value))
                self.assertEqual(ws_d2["Q38"].value, "=Q37/0.36")

                ws_hv = wb["H1"]
                self.assertEqual(ws_hv["A3"].value.strip(), '(N) PANEL "H1"')
                self.assertEqual(ws_hv["G4"].value, "200A MCB")
                self.assertEqual(ws_hv["N4"].value, "NEW")
                self.assertEqual(ws_hv["Q38"].value, "=Q37/0.831")
            finally:
                wb.close()

            # Append mode with 84-circuit panel + backup creation
            panel_84 = psa.normalize_extracted_panel(
                {
                    "panel_name": "LP84",
                    "voltage": "120/208V",
                    "bus_rating": "400A",
                    "circuits": [
                        {"circuit_number": 1, "description": "FIRST SECTION", "breaker_amps": "20", "poles": 1, "load_type": "G", "phase_kva": ["0.9"]},
                        {"circuit_number": 45, "description": "SECOND SECTION", "breaker_amps": "20", "poles": 1, "load_type": "G", "phase_kva": ["0.72"]},
                    ],
                }
            )
            res2 = psa.export_panels_to_excel(
                [panel_84],
                str(out_xlsx),
                TEMPLATE_PATH,
                mode="existing",
            )
            self.assertEqual(res2["sheets"], ["LP84 (1-42)", "LP84 (43-84)"])
            self.assertTrue(Path(res2["backupPath"]).exists())

            wb2 = openpyxl.load_workbook(out_xlsx, data_only=False)
            try:
                self.assertIn("D2", wb2.sheetnames)
                self.assertIn("LP84 (43-84)", wb2.sheetnames)
                ws_sec2 = wb2["LP84 (43-84)"]
                self.assertEqual(ws_sec2["A8"].value, 43)
                self.assertEqual(ws_sec2["A9"].value, 45)
                self.assertEqual(ws_sec2["F9"].value, "SECOND SECTION")
                self.assertEqual(ws_sec2["I9"].value, 0.72)
            finally:
                wb2.close()

            # Locked / open-in-Excel overwrite returns a clean, user-friendly message
            from unittest.mock import patch

            with patch("panel_schedule_ai.os.replace", side_effect=PermissionError(13, "Access is denied")):
                with self.assertRaises(RuntimeError) as ctx:
                    psa.export_panels_to_excel([panel_d2], str(out_xlsx), TEMPLATE_PATH, mode="new")
            self.assertIn("open in Excel", str(ctx.exception))
            self.assertNotIn(".tmp.xlsx", str(ctx.exception))

    def test_analyze_panel_groups_enforces_single_panel_per_field_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            p_tag = _make_sample_png(tmp_dir / "tag.png")
            p_brk1 = _make_sample_png(tmp_dir / "breakers_top.png")
            p_brk2 = _make_sample_png(tmp_dir / "breakers_bot.png")
            p_dir = _make_sample_png(tmp_dir / "directory.png")

            inspected = psa.inspect_sources(
                paths=[str(p_tag), str(p_brk1), str(p_brk2), str(p_dir)],
                temp_dir=tmp_dir,
            )["items"]
            # Assign explicit bucket roles (deliberately out of order to test canonical sorting)
            s_tag, s_brk1, s_brk2, s_dir = inspected
            s_tag["role"] = "nameplate"
            s_brk1["role"] = "breakers"
            s_brk1["hint"] = "1-21 & 2-22"
            s_brk2["role"] = "breakers"
            s_brk2["hint"] = "23-41 & 24-42"
            s_dir["role"] = "directory"

            captured_calls = []

            class FakeModels:
                def generate_content(self, **kwargs):
                    captured_calls.append(kwargs)
                    return types.SimpleNamespace(
                        parsed=psa.ExtractedPanelSchema(
                            panel_name="UNKNOWN",
                            voltage="120/208V",
                            bus_rating="225A",
                            main_type="MCB",
                            main_breaker_amps="200A",
                            phase="3",
                            wire="4",
                            circuits=[
                                psa.ExtractedCircuitSchema(
                                    circuit_number=1,
                                    description="OFFICE RECEPTACLES",
                                    breaker_amps="20",
                                    poles=1,
                                    load_type="G",
                                    note="1",
                                    confidence="high",
                                )
                            ],
                        ),
                        text="",
                    )

            fake_client = types.SimpleNamespace(models=FakeModels())

            res = psa.analyze_panel_groups_with_hydrogen(
                groups=[
                    {
                        "mode": "field_photos",
                        "panelName": "LP-2A",
                        "condition": "EXISTING",
                        "sources": [s_dir, s_brk1, s_tag, s_brk2],
                    }
                ],
                api_key="test-key",
                client_factory=lambda _k: fake_client,
            )

            self.assertEqual(len(captured_calls), 1)
            call = captured_calls[0]
            # Field photo group uses single-panel schema so unnamed close-ups cannot split into multiple panels
            self.assertEqual(call["config"].response_schema, psa.ExtractedPanelSchema)
            prompt_text = call["contents"][0]
            self.assertIn("PANELBOARD TAGS / NAMEPLATE LABELS", prompt_text)
            self.assertIn("CIRCUIT BREAKERS (CLOSE-UPS)", prompt_text)
            self.assertIn("PRINTED / DOOR CIRCUIT DIRECTORY", prompt_text)
            self.assertIn("1-21 & 2-22", prompt_text)
            self.assertIn("ONE SINGLE PANEL", prompt_text)

            self.assertEqual(len(res["panels"]), 1)
            panel = res["panels"][0]
            # User-supplied panel name is preserved even when close-ups had no visible name
            self.assertEqual(panel["panelName"], "LP-2A")
            # sourceIds are ordered canonically: nameplate -> breakers -> directory
            self.assertEqual(panel["sourceIds"], [s_tag["id"], s_brk1["id"], s_brk2["id"], s_dir["id"]])

    def test_sort_survey_photos_with_decision_api_buckets_and_splits_panels(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            files = [
                _make_sample_png(tmp_dir / f"IMG_{i:04d}.png")
                for i in range(1, 6)
            ]
            sources = psa.inspect_sources(paths=[str(f) for f in files], temp_dir=tmp_dir)["items"]

            captured = {}

            class FakeResponse:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {
                        "answers": {
                            "role_0": {"type": "choice", "choice": "nameplate", "confidence": 0.96},
                            "section_0": {"type": "choice", "choice": "not_applicable", "confidence": 0.99},
                            "role_1": {"type": "choice", "choice": "breakers", "confidence": 0.94},
                            "section_1": {"type": "choice", "choice": "upper_half", "confidence": 0.88},
                            "split_1": {"type": "noul", "probability": 0.08, "confidence": 0.91},
                            "role_2": {"type": "choice", "choice": "directory", "confidence": 0.64},
                            "section_2": {"type": "choice", "choice": "not_applicable", "confidence": 0.95},
                            "split_2": {"type": "noul", "probability": 0.12, "confidence": 0.89},
                            "role_3": {"type": "choice", "choice": "ignore", "confidence": 0.92},
                            "section_3": {"type": "choice", "choice": "not_applicable", "confidence": 0.99},
                            "split_3": {"type": "noul", "probability": 0.25, "confidence": 0.80},
                            "role_4": {"type": "choice", "choice": "nameplate", "confidence": 0.95},
                            "section_4": {"type": "choice", "choice": "not_applicable", "confidence": 0.99},
                            "split_4": {"type": "noul", "probability": 0.91, "confidence": 0.93},
                        }
                    }

            def fake_post(url, headers=None, json=None, timeout=None, allow_redirects=None):
                captured["url"] = url
                captured["headers"] = headers
                captured["payload"] = json
                return FakeResponse()

            res = psa.sort_survey_photos_with_decision_api(
                sources=sources,
                api_key="decision-test-key",
                split_panels=True,
                http_post=fake_post,
            )

            self.assertEqual(captured["url"], psa.GEMINI_DECISION_URL)
            self.assertEqual(captured["headers"]["x-goog-api-key"], "decision-test-key")
            self.assertEqual(captured["payload"]["model"], "gemini-decision-1")

            image_parts = [p for p in captured["payload"]["input"] if p.get("type") == "image"]
            self.assertEqual(len(image_parts), 5)
            self.assertEqual(image_parts[0]["mime_type"], "image/jpeg")
            self.assertEqual(image_parts[0]["resolution"], "low")
            self.assertTrue(len(image_parts[0]["data"]) > 20)

            self.assertEqual(res["model"], "gemini-decision-1")
            self.assertEqual(res["panelGroupCount"], 2)
            assigns = res["assignments"]
            self.assertEqual([a["bucket"] for a in assigns], ["nameplate", "breakers", "directory", "ignore", "nameplate"])
            self.assertEqual(assigns[1]["suggestedHint"], "Upper half")
            self.assertFalse(assigns[1]["lowConfidence"])
            self.assertTrue(assigns[2]["lowConfidence"])  # 0.64 < 0.72
            self.assertEqual([a["panelGroupIndex"] for a in assigns], [0, 0, 0, 0, 1])

    def test_crop_source_image_produces_full_res_cropped_copy_and_rotates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            img_path = _make_sample_png(tmp_dir / "panel_full.png", size=(1000, 800))
            src = psa.inspect_sources(paths=[str(img_path)], temp_dir=tmp_dir)["items"][0]

            # Crop a 40% x 25% region (400 x 200 px) -> assign to nameplate bucket
            cropped = psa.crop_source_image(
                src,
                {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.25},
                temp_dir=tmp_dir,
                rotation=0,
                role="nameplate",
            )
            self.assertEqual(cropped["role"], "nameplate")
            self.assertEqual(cropped["width"], 400)
            self.assertEqual(cropped["height"], 200)
            self.assertTrue(Path(cropped["path"]).exists())
            self.assertTrue(cropped["thumbDataUrl"].startswith("data:image/jpeg;base64,"))
            self.assertTrue(cropped["viewerDataUrl"].startswith("data:image/jpeg;base64,"))

            # Rotating 90 degrees swaps width & height cleanly
            rotated = psa.crop_source_image(
                src,
                {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.25},
                temp_dir=tmp_dir,
                rotation=90,
                role="nameplate",
            )
            self.assertEqual(rotated["width"], 200)
            self.assertEqual(rotated["height"], 400)

    def test_local_prefilter_drops_non_panels_keeps_sharpest_duplicate_and_tracks_gaps(self):
        import panel_photo_prefilter as pf
        from PIL import ImageDraw, ImageFilter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "SurveyPhotos"
            root.mkdir()
            (root / ".hidden").mkdir()
            _make_sample_png(root / ".hidden" / "ignored_hidden.png")

            # 1. Sharp panel photo
            img_panel = Image.new("RGB", (320, 240), (60, 60, 60))
            draw = ImageDraw.Draw(img_panel)
            for y in range(20, 220, 20):
                draw.rectangle([40, y, 280, y + 10], fill=(230, 230, 230))
            p1 = root / "01_panel_blurry.png"
            p2 = root / "02_panel_sharp.png"
            img_panel.filter(ImageFilter.GaussianBlur(radius=3)).save(p1)
            img_panel.save(p2)

            # 2. Two non-panel room/ceiling photos in between
            p3 = _make_sample_png(root / "03_room.png", color=(200, 190, 175))
            p4 = _make_sample_png(root / "04_ceiling.png", color=(235, 235, 240))

            # 3. Second distinct panel photo (different pattern so not a duplicate of p2)
            img_dir = Image.new("RGB", (320, 240), (245, 245, 245))
            draw2 = ImageDraw.Draw(img_dir)
            for x in range(30, 290, 35):
                draw2.line([(x, 20), (x, 220)], fill=(20, 20, 20), width=3)
            p5 = root / "05_directory.png"
            img_dir.save(p5)

            # Deterministic chronological timestamps
            import os

            base_t = 1_760_000_000
            for offset, fp in enumerate([p1, p2, p3, p4, p5]):
                os.utime(fp, (base_t + offset * 30, base_t + offset * 30))

            score_seq = [
                {"panelScore": 0.88, "suggestedBucket": "breakers", "bucketScore": 0.7, "topNegativeLabel": "Room / Interior", "topNegativeScore": 0.12},
                {"panelScore": 0.91, "suggestedBucket": "breakers", "bucketScore": 0.8, "topNegativeLabel": "Room / Interior", "topNegativeScore": 0.09},
                {"panelScore": 0.08, "suggestedBucket": "nameplate", "bucketScore": 0.3, "topNegativeLabel": "Room / Interior", "topNegativeScore": 0.92},
                {"panelScore": 0.05, "suggestedBucket": "nameplate", "bucketScore": 0.3, "topNegativeLabel": "Ceiling / Lighting", "topNegativeScore": 0.95},
                {"panelScore": 0.85, "suggestedBucket": "directory", "bucketScore": 0.75, "topNegativeLabel": "Room / Interior", "topNegativeScore": 0.15},
            ]
            cursor = [0]

            def fake_scorer(batch_pils):
                out = score_seq[cursor[0] : cursor[0] + len(batch_pils)]
                cursor[0] += len(batch_pils)
                return out

            res = pf.prefilter_survey_photos(
                [root],
                sensitivity="balanced",
                dedupe=True,
                scorer_fn=fake_scorer,
            )

            stats = res["stats"]
            self.assertEqual(stats["totalScanned"], 5)
            self.assertEqual(stats["keptCount"], 2)
            self.assertEqual(stats["nonPanelDropped"], 2)
            self.assertEqual(stats["duplicateDropped"], 1)

            kept = res["kept"]
            # Sharp duplicate p2 won over blurry p1!
            self.assertEqual(kept[0]["name"], "02_panel_sharp.png")
            self.assertEqual(kept[1]["name"], "05_directory.png")
            # Second panel photo records the 2 dropped non-panel photos + 90s elapsed in between
            self.assertEqual(kept[1]["nonPanelGapBefore"], 2)
            self.assertEqual(kept[1]["gapSecondsBefore"], 90)

            dropped_names = {d["name"]: d["dropCategory"] for d in res["dropped"]}
            self.assertEqual(dropped_names["01_panel_blurry.png"], "duplicate")
            self.assertEqual(dropped_names["03_room.png"], "non_panel")
            self.assertEqual(dropped_names["04_ceiling.png"], "non_panel")

    def test_custom_classifier_trainer_and_labeler_session(self):
        import numpy as np
        import panel_photo_prefilter as pf
        from scripts import panel_photo_labeler as labeler
        from scripts import train_panel_classifier as trainer

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            raw_dir = tmp_dir / "survey_raw"
            raw_dir.mkdir()
            p1 = _make_sample_png(raw_dir / "a.png", color=(20, 20, 20))
            p2 = _make_sample_png(raw_dir / "b.png", color=(220, 220, 220))

            dataset_dir = tmp_dir / "dataset"
            session = labeler.LabelerSession(dataset_dir)
            added = session.add_folder(str(raw_dir))
            self.assertEqual(added["added"], 2)

            st1 = session.get_state()
            first_id = st1["upcoming"][0]["id"]
            st2 = session.label_current(first_id, ["panel_tag", "breakers"])
            self.assertEqual(st2["counts"]["panel_tag"], 1)
            self.assertEqual(st2["counts"]["breakers"], 1)
            self.assertEqual(st2["counts"]["multi_tag"], 1)
            self.assertEqual(st2["counts"]["panel_any"], 1)
            self.assertEqual(st2["queueRemaining"], 1)
            self.assertTrue(st2["canUndo"])
            self.assertTrue((dataset_dir / "labels.json").exists())

            # Re-adding the same folder skips already-labeled photo
            added_again = session.add_folder(str(raw_dir))
            self.assertEqual(added_again["added"], 0)
            self.assertEqual(added_again["skippedAlreadyLabeled"], 2)

            # Queue existing tag for quick re-labeling (e.g. split nameplate -> wiring_label)
            q_res = session.queue_existing_by_tag("panel_tag")
            self.assertEqual(q_res["queued"], 1)
            self.assertTrue(q_res["state"]["upcoming"][0]["existing"])
            st_relabel = session.label_current(first_id, ["wiring_label"])
            self.assertEqual(st_relabel["counts"]["panel_tag"], 0)
            self.assertEqual(st_relabel["counts"]["wiring_label"], 1)

            # Undo re-label restores previous tags without deleting the dataset image
            st_undo_relabel = session.undo_last()
            self.assertEqual(st_undo_relabel["counts"]["panel_tag"], 1)
            self.assertEqual(st_undo_relabel["counts"]["wiring_label"], 0)
            # Remove the re-queued existing item by skipping it, then undo original label
            session.label_current(first_id, [], skip=True)
            session.undo_last()
            # Clear queue and undo the original label
            session.queue.pop(0)
            st3 = session.undo_last()
            self.assertEqual(st3["counts"]["breakers"], 0)
            self.assertEqual(st3["counts"]["panel_tag"], 0)
            self.assertEqual(st3["counts"]["multi_tag"], 0)
            self.assertEqual(st3["queueRemaining"], 2)
            self.assertEqual(st3["upcoming"][0]["id"], first_id)

            # Train custom 7-head multi-label classifier on separable synthetic embeddings:
            # [is_panel, panel_tag, nameplate, wiring_label, breakers, directory, main_breaker]
            rng = np.random.default_rng(7)
            proto = rng.normal(size=(8, 512)).astype(np.float32)
            proto /= np.linalg.norm(proto, axis=1, keepdims=True)
            combos = [
                (0, [1, 1, 0, 0, 0, 0, 0], 10),  # panel_tag only
                (1, [1, 0, 1, 0, 0, 0, 0], 10),  # nameplate only
                (2, [1, 0, 0, 1, 0, 0, 0], 10),  # wiring_label only
                (3, [1, 0, 0, 0, 1, 0, 0], 10),  # breakers only
                (4, [1, 0, 0, 0, 0, 1, 0], 10),  # directory only
                (5, [1, 0, 0, 0, 0, 0, 1], 10),  # main_breaker only
                (6, [1, 1, 0, 0, 1, 1, 1], 12),  # full_panel (tag+breakers+directory+main)
                (7, [0, 0, 0, 0, 0, 0, 0], 28),  # not_panel
            ]
            X_parts, Y_parts = [], []
            for p_idx, y_vec, n_c in combos:
                pts = proto[p_idx] + rng.normal(scale=0.04, size=(n_c, 512)).astype(np.float32)
                pts /= np.linalg.norm(pts, axis=1, keepdims=True)
                X_parts.append(pts)
                Y_parts.append(np.tile(np.array(y_vec, dtype=np.float32), (n_c, 1)))
            # Also add a mixed panel_tag + breakers combo
            mix_dir = (proto[0] + proto[3]) / np.linalg.norm(proto[0] + proto[3])
            mix_pts = mix_dir + rng.normal(scale=0.03, size=(8, 512)).astype(np.float32)
            mix_pts /= np.linalg.norm(mix_pts, axis=1, keepdims=True)
            X_parts.append(mix_pts)
            Y_parts.append(np.tile(np.array([1, 1, 0, 0, 1, 0, 0], dtype=np.float32), (8, 1)))

            X = np.vstack(X_parts)
            Y = np.vstack(Y_parts)
            counts = {
                "total": int(len(Y)),
                "panel_any": int(np.sum(Y[:, 0] > 0.5)),
                "not_panel": int(np.sum(Y[:, 0] <= 0.5)),
                "multi_tag": 20,
                **{tag: int(np.sum(Y[:, idx] > 0.5)) for idx, tag in enumerate(trainer.TAG_NAMES, start=1)},
            }

            model_dir = tmp_dir / "model_cache"
            out_npz = pf.get_custom_classifier_path(model_dir)
            train_res = trainer.train_from_dataset(
                dataset_dir,
                output_path=out_npz,
                embeddings_override=(X, Y, counts),
            )
            self.assertTrue(out_npz.exists())
            metrics = train_res["metadata"]["metrics"]
            self.assertGreaterEqual(metrics["panelF1"], 0.95)
            self.assertGreaterEqual(metrics["macroTagF1"], 0.90)

            loaded = pf.load_custom_classifier(model_dir)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["mode"], "multilabel_sigmoid")
            self.assertEqual(loaded["weights"].shape, (7, 512))
            self.assertEqual(loaded["metadata"]["sampleCount"], 108)

    def test_ui_and_packaging_wiring_is_complete_and_csp_safe(self):
        html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
        js = (REPO_ROOT / "panel_schedule_ai_ui.js").read_text(encoding="utf-8")
        main_script = (REPO_ROOT / "script.js").read_text(encoding="utf-8")
        spec = (REPO_ROOT / "ACIES Scheduler.spec").read_text(encoding="utf-8")

        self.assertIn('id="toolPanelScheduleStudio"', html)
        self.assertIn('id="panelStudioDlg"', html)
        self.assertIn('id="psaAutoSortBar"', html)
        self.assertIn('id="psaPrefilterFolderBtn"', html)
        self.assertIn('id="psaPrefilterSensitivity"', html)
        self.assertIn('id="psaLocalModelStatus"', html)
        self.assertIn('id="psaAutoSortSplitCb"', html)
        self.assertIn('id="psaIgnoredTray"', html)
        self.assertIn('id="psaLightboxOverlay"', html)
        self.assertIn('id="psaBgProgressBanner"', html)
        self.assertIn('id="psaTokenAdvisor"', html)
        self.assertIn('id="psaReadyToast"', html)
        self.assertIn('id="psaFlagCheckOverlay"', html)
        self.assertIn('data-bucket="nameplate"', html)
        self.assertIn('data-bucket="breakers"', html)
        self.assertIn('data-bucket="directory"', html)
        self.assertIn('data-bucket="main_breaker"', html)
        self.assertIn('data-bucket="full_panel"', html)
        self.assertIn("panel_schedule_ai.css", html)
        self.assertIn("panel_schedule_ai_ui.js", html)
        # Ensure zero inline onclick handlers in new dialog markup
        dlg_start = html.index('<dialog id="panelStudioDlg"')
        dlg_end = html.index("</dialog>", dlg_start)
        self.assertNotIn("onclick=", html[dlg_start:dlg_end].lower())

        self.assertIn("window.openPanelScheduleStudio = openPanelScheduleStudio;", js)
        self.assertIn("panel_studio_start_prefilter", js)
        self.assertIn("panel_studio_auto_sort_photos", js)
        self.assertIn("panel_studio_crop_source", js)
        self.assertIn("panel_studio_start_analyze", js)
        self.assertIn("panel_studio_get_job_status", js)
        self.assertIn("panel_studio_analyze", js)
        self.assertIn("panel_studio_export_excel", js)

        self.assertIn('id: "toolPanelScheduleStudio"', main_script)
        self.assertIn("('panel_schedule_ai.css', '.')", spec)
        self.assertIn("('panel_schedule_ai_ui.js', '.')", spec)

        css = (REPO_ROOT / "panel_schedule_ai.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: minmax(0, 1fr);", css)


if __name__ == "__main__":
    unittest.main()
