"""Automated Panel Schedule AI Studio powered by Gemini 4 Hydrogen.

Workflow:
1. Inspect local photos (JPG/PNG/HEIC/TIFF/WEBP) and as-built record PDFs
   (rendered via PyMuPDF) to produce preview thumbnails and high-resolution
   source images for review and AI vision.
2. Send selected images/PDF pages to Gemini 4 Hydrogen (``gemini-4-hydrogen``)
   with a structured Pydantic schema supporting both single-panel site survey
   photo sets and multi-panel as-built electrical drawings.
3. Return normalized, validated panel schedules with per-circuit confidence and
   review notes so the engineer can inspect and edit side-by-side before export.
4. Export reviewed panels cleanly into ACIES ``Template.xlsx`` (creating a new
   ``.xlsx``/``.xls`` workbook starting from only the ``TEMPLATE`` sheet, or
   appending/updating sheets in an existing project workbook) while preserving
   all formatting and NEC demand-load formulas.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Primary model requested for Panel Schedule AI Studio (Google AI Studio Free Tier).
GEMINI_HYDROGEN_MODEL = "gemini-4-hydrogen"
DEFAULT_STUDIO_MODELS = (GEMINI_HYDROGEN_MODEL,)

# Fast multimodal classifier for pre-sorting raw site survey photos into buckets.
GEMINI_DECISION_MODEL = "gemini-decision-1"
GEMINI_DECISION_URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
DECISION_SORT_MAX_EDGE = 768
DECISION_SORT_BATCH_SIZE = 18
DECISION_LOW_CONFIDENCE_THRESHOLD = 0.72
DECISION_PANEL_SPLIT_THRESHOLD = 0.65
DECISION_VALID_BUCKETS = ("nameplate", "breakers", "directory", "main_breaker", "full_panel", "ignore")
DECISION_SECTION_HINTS = {
    "upper_half": "Upper half",
    "middle_section": "Middle section",
    "lower_half": "Lower half",
}

STUDIO_MAX_ANALYSIS_IMAGE_EDGE = 2048
STUDIO_MAX_VIEWER_IMAGE_EDGE = 3200
STUDIO_MAX_THUMB_EDGE = 320
STUDIO_PDF_THUMB_DPI = 72
STUDIO_PDF_ANALYSIS_DPI = 200
STUDIO_PDF_MAX_EDGE = 2800
STUDIO_REQUEST_TIMEOUT_MS = 300000
STUDIO_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_SOURCE_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS

SOURCE_ROLES = (
    "auto",
    "as_built_drawing",
    "breakers",
    "directory",
    "nameplate",
    "main_breaker",
    "full_panel",
)
VALID_LOAD_TYPES = {"", "C", "D", "G", "K", "M", "ML"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_CONDITIONS = {"EXISTING", "NEW"}
TEMPLATE_EXAMPLE_SHEETS_TO_PRUNE = {
    "HPT",
    "A (2)",
    "_NOTES",
    "Ax",
    "Bx",
    "L109C_NOTUSED",
}

# Exact column mapping of CircuitBreakerAI/ElectricalPanels/Template.xlsx -> TEMPLATE sheet.
COL_L_NOTE = "B"
COL_L_TYPE = "C"
COL_L_POLE = "D"
COL_L_TRIP = "E"
COL_L_DESC = "F"
COL_L_KVA = "I"
COL_PHASE = "J"
COL_R_KVA = "K"
COL_R_DESC = "L"
COL_R_POLE = "O"
COL_R_TRIP = "P"
COL_R_TYPE = "Q"
COL_R_NOTE = "R"
START_ROW = 8
MAX_ROW = 28
SLOTS_PER_SHEET = 42

_HEIF_REGISTERED = False


def _ensure_heif_support() -> None:
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        pass
    _HEIF_REGISTERED = True


# ---------------------------------------------------------------------------
# Structured Gemini Output Schemas
# ---------------------------------------------------------------------------


class ExtractedCircuitSchema(BaseModel):
    circuit_number: int = Field(
        ...,
        description="Top-most circuit number occupied by this breaker (odd=left, even=right, 1..84).",
    )
    description: str = Field(
        "",
        description="Load description (resolve ditto marks). Use 'SPARE' or 'SPACE' when applicable.",
    )
    breaker_amps: str = Field(
        "",
        description="Breaker trip rating as digits only (e.g. '20', '30', '100'), or '' for SPACE.",
    )
    poles: int = Field(
        1,
        description="Number of poles (1, 2, or 3). Use 0 for empty SPACE with no breaker installed.",
    )
    load_type: str = Field(
        "",
        description="ACIES load code: 'C', 'D', 'G', 'K', 'M', 'ML', or '' for SPARE/SPACE.",
    )
    note: str = Field(
        "1",
        description="Circuit note code if shown (e.g. '1', '2', '3', '1,LO'). Default '1' for existing breakers, '' for SPACE.",
    )
    phase_kva: List[str] = Field(
        default_factory=list,
        description="Ordered visible kVA decimals for each occupied row top-to-bottom (e.g. ['0.9'] or ['2.3', '2.3']). Blank if not visible.",
    )
    kva: str = Field(
        "",
        description="Single visible kVA value only if no per-row phase_kva breakdown is shown. Never estimate or invent.",
    )
    confidence: str = Field(
        "high",
        description="'high', 'medium', or 'low' based on legibility and certainty.",
    )
    review_note: str = Field(
        "",
        description="Short reason whenever confidence is 'medium' or 'low' (e.g. 'Glare on breaker handle', 'Handwriting unclear').",
    )


class ExtractedPanelSchema(BaseModel):
    panel_name: str = Field(
        ...,
        description="Panel designation without prefix, e.g. 'A', 'D1', 'LP-1', 'MDP'.",
    )
    source_kind: str = Field(
        "as_built_drawing",
        description="'as_built_drawing', 'field_photos', or 'mixed'.",
    )
    source_indices: List[int] = Field(
        default_factory=list,
        description="Zero-based indices of the provided input images that contain evidence for this panel.",
    )
    voltage: str = Field(
        "",
        description="Panel voltage (e.g. '120/208V', '277/480V', '120/240V'). Blank if unknown.",
    )
    bus_rating: str = Field(
        "",
        description="Main bus amp rating (e.g. '100A', '225A', '400A'). Blank if unknown.",
    )
    main_type: str = Field(
        "",
        description="'MLO' or 'MCB' (or short device type if clearly shown), else ''.",
    )
    main_breaker_amps: str = Field(
        "",
        description="Main breaker amp rating if MCB (e.g. '200A'), else ''.",
    )
    phase: str = Field(
        "",
        description="Number of phases as a digit string: '3' or '1'.",
    )
    wire: str = Field(
        "",
        description="Number of wires as a digit string: '4' or '3'.",
    )
    mounting: str = Field(
        "",
        description="'SURFACE', 'FLUSH', or 'RECESSED' when visible, else ''.",
    )
    enclosure: str = Field(
        "",
        description="'NEMA 1', 'NEMA 3R', etc. when visible, else ''.",
    )
    aic_rating: str = Field(
        "",
        description="Panel AIC rating when visible (e.g. '10 KAIC', '22,000 AIC', 'EXISTING'), else ''.",
    )
    condition: str = Field(
        "EXISTING",
        description="'EXISTING' or 'NEW'. Default 'EXISTING' for site surveys and as-built panels.",
    )
    fed_from: str = Field(
        "",
        description="Feeder source if visible (e.g. \"FED FROM PANEL 'D2'\", 'FED FROM MDP', 'FED FROM MAIN SERVICE'), else ''.",
    )
    circuit_count: int = Field(
        42,
        description="Total number of circuit spaces in the panel (typically 30, 42, 60, or 84).",
    )
    header_warnings: List[str] = Field(
        default_factory=list,
        description="Short warnings for unreadable, conflicting, or missing header values.",
    )
    notes: str = Field(
        "",
        description="Brief 1-2 sentence extraction summary or field observation for the engineer.",
    )
    circuits: List[ExtractedCircuitSchema] = Field(
        default_factory=list,
        description="Detected circuits/breakers in this panel.",
    )


class ExtractedPanelBatchSchema(BaseModel):
    panels: List[ExtractedPanelSchema] = Field(
        default_factory=list,
        description="All electrical panels detected across the provided images/pages.",
    )
    overall_notes: str = Field(
        "",
        description="Optional short summary covering the extraction batch.",
    )


# ---------------------------------------------------------------------------
# Image & PDF Inspection / Rendering Helpers
# ---------------------------------------------------------------------------


def _pil_to_data_url(img, *, fmt: str = "JPEG", quality: int = 84) -> str:
    buf = io.BytesIO()
    save_img = img
    if fmt.upper() == "JPEG" and save_img.mode not in ("RGB", "L"):
        save_img = save_img.convert("RGB")
    save_kwargs: Dict[str, Any] = {"format": fmt}
    if fmt.upper() == "JPEG":
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
    save_img.save(buf, **save_kwargs)
    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _compute_image_dhash(img) -> str:
    """Compute a fast 64-bit perceptual difference hash (16 hex chars) for duplicate detection."""
    try:
        from PIL import Image

        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
        gray = img.convert("L").resize((9, 8), resample)
        pixels = gray.tobytes()
        bits = 0
        for row in range(8):
            offset = row * 9
            for col in range(8):
                bits = (bits << 1) | (1 if pixels[offset + col] > pixels[offset + col + 1] else 0)
        return f"{bits:016x}"
    except Exception:
        return ""


def _resize_pil_image(img, max_edge: int):
    from PIL import Image

    width, height = img.size
    longest = max(width, height)
    if longest <= max_edge or max_edge <= 0:
        return img
    scale = max_edge / float(longest)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
    return img.resize(new_size, resample)


def _open_normalized_pil(path: Path, max_edge: int):
    from PIL import Image, ImageOps

    _ensure_heif_support()
    with Image.open(path) as raw:
        # Fast libjpeg DCT downscale when reading thumbnails from large camera JPEGs
        if max_edge > 0 and max_edge <= 640 and getattr(raw, "format", "") == "JPEG":
            try:
                raw.draft("RGB", (max_edge * 2, max_edge * 2))
            except Exception:
                pass
        img = ImageOps.exif_transpose(raw)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        elif img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.copy()
    return _resize_pil_image(img, max_edge)


def _decode_base64_payload(data_url_or_b64: str) -> bytes:
    raw = str(data_url_or_b64 or "").strip()
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def _open_pil_from_bytes(payload: bytes, max_edge: int):
    from PIL import Image, ImageOps

    _ensure_heif_support()
    with Image.open(io.BytesIO(payload)) as raw:
        img = ImageOps.exif_transpose(raw)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        elif img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.copy()
    return _resize_pil_image(img, max_edge)


def _render_pdf_page_to_pil(pdf_path: Path, page_index: int, dpi: int, max_edge: int):
    import pymupdf
    from PIL import Image

    doc = pymupdf.open(str(pdf_path))
    try:
        if page_index < 0 or page_index >= len(doc):
            raise IndexError(f"PDF page {page_index + 1} is out of range for {pdf_path.name}.")
        page = doc[page_index]
        rect = page.rect
        zoom = dpi / 72.0
        longest_px = max(rect.width, rect.height) * zoom
        if max_edge > 0 and longest_px > max_edge:
            zoom = max_edge / max(rect.width, rect.height, 1.0)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img
    finally:
        doc.close()


def _detect_pdf_page_label(page, page_index: int) -> str:
    try:
        label = str(page.get_label() or "").strip()
    except Exception:
        label = ""
    if label:
        return f"Page {page_index + 1} ({label})"
    return f"Page {page_index + 1}"


def inspect_sources(
    paths: Optional[Sequence[str]] = None,
    uploads: Optional[Sequence[Dict[str, Any]]] = None,
    temp_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Inspect local files and/or uploaded payloads (images & PDFs) for the UI.

    For PDFs, each page becomes a selectable source item with a preview thumbnail
    and high-res viewer image generated lazily or on inspection.
    For images (including HEIC), each image gets a thumbnail and viewer image.
    """
    items: List[Dict[str, Any]] = []
    warnings: List[str] = []

    resolved_files: List[Tuple[Path, str, bool]] = []
    for raw_path in paths or []:
        text = str(raw_path or "").strip()
        if not text:
            continue
        p = Path(text)
        if not p.exists() or not p.is_file():
            warnings.append(f"File not found: {text}")
            continue
        resolved_files.append((p, p.name, False))

    if uploads:
        upload_root = Path(temp_dir) if temp_dir else Path(tempfile.mkdtemp(prefix="acies_panel_studio_"))
        upload_root.mkdir(parents=True, exist_ok=True)
        for idx, entry in enumerate(uploads):
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or f"upload_{idx + 1}.png").strip()
            safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name) or f"upload_{idx + 1}.png"
            ext = Path(safe_name).suffix.lower() or ".png"
            if ext not in SUPPORTED_SOURCE_EXTENSIONS:
                warnings.append(f"Unsupported file skipped: {name}")
                continue
            b64 = entry.get("dataUrl") or entry.get("data") or entry.get("base64") or ""
            if not b64:
                continue
            try:
                raw_bytes = _decode_base64_payload(b64)
            except Exception as exc:
                warnings.append(f"Could not decode {name}: {exc}")
                continue
            dest = upload_root / f"{uuid.uuid4().hex[:10]}_{safe_name}"
            dest.write_bytes(raw_bytes)
            resolved_files.append((dest, name, True))

    for file_path, display_name, is_temp in resolved_files:
        ext = file_path.suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            try:
                viewer_img = _open_normalized_pil(file_path, STUDIO_MAX_VIEWER_IMAGE_EDGE)
                thumb_img = _resize_pil_image(viewer_img, STUDIO_MAX_THUMB_EDGE)
                width, height = viewer_img.size
                items.append(
                    {
                        "id": f"src_{uuid.uuid4().hex[:10]}",
                        "kind": "image",
                        "name": display_name,
                        "path": str(file_path),
                        "isTemp": is_temp,
                        "pageIndex": None,
                        "pageCount": 1,
                        "pageLabel": display_name,
                        "selected": True,
                        "role": "auto",
                        "hint": "",
                        "width": width,
                        "height": height,
                        "dhash": _compute_image_dhash(thumb_img),
                        "thumbDataUrl": _pil_to_data_url(thumb_img, fmt="JPEG", quality=78),
                        "viewerDataUrl": _pil_to_data_url(viewer_img, fmt="JPEG", quality=86),
                    }
                )
            except Exception as exc:
                warnings.append(f"Could not read image {display_name}: {exc}")
        elif ext in PDF_EXTENSIONS:
            try:
                import pymupdf
                from PIL import Image

                doc = pymupdf.open(str(file_path))
                try:
                    page_count = len(doc)
                    if page_count == 0:
                        warnings.append(f"PDF has no pages: {display_name}")
                        continue
                    for page_idx in range(page_count):
                        page = doc[page_idx]
                        page_label = _detect_pdf_page_label(page, page_idx)
                        # Thumbnail render
                        zoom = STUDIO_PDF_THUMB_DPI / 72.0
                        longest = max(page.rect.width, page.rect.height) * zoom
                        if longest > STUDIO_MAX_THUMB_EDGE:
                            zoom = STUDIO_MAX_THUMB_EDGE / max(page.rect.width, page.rect.height, 1.0)
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                        thumb_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                        # Auto-select pages only when a small PDF (<= 4 pages) or when text looks like a panel schedule
                        page_text = ""
                        try:
                            page_text = (page.get_text("text") or "").upper()
                        except Exception:
                            page_text = ""
                        looks_like_panel = any(
                            kw in page_text
                            for kw in (
                                "PANEL SCHEDULE",
                                "LOAD DESCRIPTION",
                                "CKT#",
                                "CIRCUIT",
                                "BUS RATING",
                                "CONNECTED LOAD",
                                "PANEL '",
                                'PANEL "',
                            )
                        )
                        default_selected = page_count <= 4 or looks_like_panel

                        items.append(
                            {
                                "id": f"src_{uuid.uuid4().hex[:10]}",
                                "kind": "pdf_page",
                                "name": display_name,
                                "path": str(file_path),
                                "isTemp": is_temp,
                                "pageIndex": page_idx,
                                "pageCount": page_count,
                                "pageLabel": f"{display_name} — {page_label}",
                                "shortPageLabel": page_label,
                                "selected": default_selected,
                                "looksLikePanel": looks_like_panel,
                                "role": "as_built_drawing",
                                "hint": "",
                                "width": int(round(page.rect.width)),
                                "height": int(round(page.rect.height)),
                                "dhash": _compute_image_dhash(thumb_img),
                                "thumbDataUrl": _pil_to_data_url(thumb_img, fmt="JPEG", quality=80),
                                "viewerDataUrl": "",
                            }
                        )
                finally:
                    doc.close()
            except Exception as exc:
                warnings.append(f"Could not read PDF {display_name}: {exc}")
        else:
            warnings.append(f"Unsupported file format: {display_name}")

    # If a large PDF had no text-detected panel sheets (scanned drawing), select page 1 by default.
    if items and not any(item.get("selected") for item in items):
        items[0]["selected"] = True

    return {"items": items, "warnings": warnings}


def render_source_viewer_image(source: Dict[str, Any], max_edge: int = STUDIO_MAX_VIEWER_IMAGE_EDGE) -> str:
    """Return a high-resolution data URL for viewing a source image or PDF page."""
    existing = str(source.get("viewerDataUrl") or "").strip()
    if existing:
        return existing
    path = Path(str(source.get("path") or ""))
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    kind = str(source.get("kind") or "image")
    if kind == "pdf_page":
        page_index = int(source.get("pageIndex") or 0)
        img = _render_pdf_page_to_pil(path, page_index, dpi=240, max_edge=max_edge)
        return _pil_to_data_url(img, fmt="JPEG", quality=90)
    img = _open_normalized_pil(path, max_edge)
    return _pil_to_data_url(img, fmt="JPEG", quality=90)


def crop_source_image(
    source: Dict[str, Any],
    rect: Dict[str, Any],
    *,
    temp_dir: Optional[Path] = None,
    rotation: int = 0,
    role: str = "",
) -> Dict[str, Any]:
    """Create a full-resolution cropped image from a source photo or PDF page.

    ``rect`` uses normalized coordinates ``x, y, w, h`` in ``[0, 1]`` relative to the
    (optionally clockwise-rotated) source image.
    """
    path = Path(str(source.get("path") or ""))
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    try:
        rx = float(rect.get("x", 0.0))
        ry = float(rect.get("y", 0.0))
        rw = float(rect.get("w", 0.0))
        rh = float(rect.get("h", 0.0))
    except Exception as exc:
        raise ValueError("Invalid crop coordinates.") from exc

    rx = max(0.0, min(1.0, rx))
    ry = max(0.0, min(1.0, ry))
    rw = max(0.0, min(1.0 - rx, rw))
    rh = max(0.0, min(1.0 - ry, rh))
    if rw <= 0.005 or rh <= 0.005:
        raise ValueError("Draw a larger crop region before saving.")

    kind = str(source.get("kind") or "image")
    if kind == "pdf_page":
        page_index = int(source.get("pageIndex") or 0)
        base_img = _render_pdf_page_to_pil(path, page_index, dpi=260, max_edge=4096)
    else:
        base_img = _open_normalized_pil(path, max_edge=4096)

    try:
        img_w, img_h = base_img.size
        left = int(round(rx * img_w))
        top = int(round(ry * img_h))
        right = int(round((rx + rw) * img_w))
        bottom = int(round((ry + rh) * img_h))
        left = max(0, min(img_w - 1, left))
        top = max(0, min(img_h - 1, top))
        right = max(left + 1, min(img_w, right))
        bottom = max(top + 1, min(img_h, bottom))
        if (right - left) < 12 or (bottom - top) < 12:
            raise ValueError("Selected crop area is too small. Draw a wider selection.")

        cropped = base_img.crop((left, top, right, bottom))
        rot = int(rotation or 0) % 360
        if rot:
            # PIL rotates counter-clockwise; CSS rotates clockwise.
            cropped = cropped.rotate(-rot, expand=True)
        out_root = Path(temp_dir) if temp_dir else Path(tempfile.mkdtemp(prefix="acies_panel_crop_"))
        out_root.mkdir(parents=True, exist_ok=True)
        orig_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", Path(str(source.get("name") or path.name)).stem).strip(" ._") or "photo"
        out_name = f"{orig_stem}_crop.jpg"
        out_path = out_root / f"crop_{uuid.uuid4().hex[:10]}_{orig_stem}.jpg"
        save_rgb = cropped.convert("RGB") if cropped.mode not in ("RGB", "L") else cropped
        save_rgb.save(out_path, format="JPEG", quality=94, optimize=True)

        viewer_img = _resize_pil_image(save_rgb, STUDIO_MAX_VIEWER_IMAGE_EDGE)
        thumb_img = _resize_pil_image(save_rgb, STUDIO_MAX_THUMB_EDGE)
        final_role = str(role or source.get("role") or "auto").strip()
        base_label = str(source.get("pageLabel") or source.get("name") or path.name)
        crop_label = base_label if "(crop)" in base_label.lower() else f"{base_label} (crop)"

        return {
            "id": f"src_{uuid.uuid4().hex[:10]}",
            "kind": "image",
            "name": out_name,
            "path": str(out_path),
            "isTemp": True,
            "pageIndex": None,
            "pageCount": 1,
            "pageLabel": crop_label,
            "selected": True,
            "role": final_role,
            "hint": "",
            "width": save_rgb.size[0],
            "height": save_rgb.size[1],
            "dhash": _compute_image_dhash(thumb_img),
            "thumbDataUrl": _pil_to_data_url(thumb_img, fmt="JPEG", quality=82),
            "viewerDataUrl": _pil_to_data_url(viewer_img, fmt="JPEG", quality=92),
        }
    finally:
        try:
            base_img.close()
        except Exception:
            pass


def _open_source_for_analysis(source: Dict[str, Any]):
    path = Path(str(source.get("path") or ""))
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    kind = str(source.get("kind") or "image")
    if kind == "pdf_page":
        page_index = int(source.get("pageIndex") or 0)
        return _render_pdf_page_to_pil(
            path,
            page_index,
            dpi=STUDIO_PDF_ANALYSIS_DPI,
            max_edge=STUDIO_PDF_MAX_EDGE,
        )
    return _open_normalized_pil(path, STUDIO_MAX_ANALYSIS_IMAGE_EDGE)


# ---------------------------------------------------------------------------
# Normalization, Validation & NEC Load Calculations
# ---------------------------------------------------------------------------


def clean_upper(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().upper()


def parse_int_digits(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(round(value))
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else None


def normalize_kva_value(raw_kva: Any) -> Optional[float]:
    if raw_kva is None or isinstance(raw_kva, bool):
        return None
    if isinstance(raw_kva, (int, float)):
        val = float(raw_kva)
    else:
        text = str(raw_kva).strip()
        if not text:
            return None
        upper = text.upper()
        if upper in {"N/A", "NA", "NONE", "UNKNOWN", "UNREADABLE", "BLANK", "-", "--", "---"}:
            return None
        m = re.search(r"[-+]?\d+(?:\.\d+)?", upper.replace(",", ""))
        if not m:
            return None
        try:
            val = float(m.group(0))
        except Exception:
            return None
        if "VA" in upper and "KVA" not in upper and val >= 10:
            val = val / 1000.0
    if not math.isfinite(val) or val < 0:
        return None
    return round(val, 3)


def normalize_panel_name(raw_name: Any, fallback: str = "A") -> str:
    text = clean_upper(raw_name)
    text = re.sub(r'^\([EN]\)\s*', "", text)
    text = re.sub(r'^PANEL\s*', "", text)
    text = text.strip(" '\"\t\r\n")
    return text or fallback


def normalize_voltage(raw_voltage: Any) -> str:
    text = clean_upper(raw_voltage)
    if not text:
        return ""
    compact = text.replace(" ", "")
    if "480" in compact and "277" in compact:
        return "277/480V"
    if "208" in compact and "120" in compact:
        return "120/208V"
    if "240" in compact and "120" in compact:
        return "120/240V"
    if re.fullmatch(r"\d+(?:/\d+)?", compact):
        return f"{compact}V"
    return text


def normalize_bus_rating(raw_bus: Any) -> str:
    text = clean_upper(raw_bus)
    if not text:
        return ""
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if m and (text.endswith("A") or text.endswith("AMPS") or text.endswith("AMP") or m.group(0) == text):
        num = m.group(1)
        return f"{num}A"
    return text


def normalize_enclosure(raw_enclosure: Any) -> str:
    text = clean_upper(raw_enclosure)
    if not text:
        return "NEMA 1"
    if any(token in text for token in ("3R", "OUTDOOR", "EXTERIOR", "WEATHER", "WP")):
        return "NEMA 3R"
    if "4X" in text:
        return "NEMA 4X"
    if "12" in text:
        return "NEMA 12"
    if "NEMA" in text:
        return text
    return "NEMA 1"


def normalize_mounting(raw_mounting: Any) -> str:
    text = clean_upper(raw_mounting)
    if not text:
        return "SURFACE"
    if "FLUSH" in text:
        return "FLUSH"
    if "RECESS" in text:
        return "RECESSED"
    if "SURF" in text:
        return "SURFACE"
    return text


def normalize_fed_from(raw_fed_from: Any) -> str:
    text = clean_upper(raw_fed_from)
    if not text:
        return ""
    if not text.startswith("FED FROM"):
        return f"FED FROM {text}"
    return text


def format_main_requirement(main_type: str, main_amps: str) -> str:
    m_type = clean_upper(main_type)
    m_amps = clean_upper(main_amps)
    if m_amps and re.fullmatch(r"\d+(?:\.\d+)?", m_amps):
        m_amps = f"{m_amps}A"
    if m_type == "MLO" and not m_amps:
        return "MLO"
    if m_type == "MLO" and m_amps:
        return f"{m_amps} MLO"
    if m_amps and m_type:
        return f"{m_amps} {m_type}"
    if m_amps:
        return f"{m_amps} MCB"
    return m_type or "MLO"


def infer_phase_and_wire(voltage: str, phase: Any, wire: Any) -> Tuple[int, int]:
    p = parse_int_digits(phase)
    w = parse_int_digits(wire)
    v = clean_upper(voltage)
    if p not in (1, 3):
        if "240" in v and "120" in v and "480" not in v:
            p = 1
        else:
            p = 3
    if w not in (2, 3, 4):
        w = 4 if p == 3 else 3
    return p, w


def voltage_amps_divisor(voltage: str, phase: int) -> float:
    """Return kVA -> Amps divisor matching ACIES Template.xlsx Q38 conventions."""
    v = clean_upper(voltage)
    if phase == 1:
        if "208" in v:
            return 0.208
        if "277" in v:
            return 0.277
        if "480" in v:
            return 0.48
        return 0.24  # 120/240V 1-phase
    # 3-phase
    if "480" in v or "277" in v:
        return 0.831  # sqrt(3) * 480 / 1000
    if "240" in v and "208" not in v:
        return 0.416  # sqrt(3) * 240 / 1000
    return 0.36  # sqrt(3) * 208 / 1000 (standard ACIES template value)


def line_to_neutral_voltage(voltage: str) -> float:
    v = clean_upper(voltage)
    if "480" in v or "277" in v:
        return 277.0
    return 120.0


def _resolve_ditto_dicts(circuits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ditto_re = re.compile(r'^["\'\u2018\u2019\u201c\u201d\.]+$|^(SAME|DO|DITTO)$', re.IGNORECASE)
    odds = sorted([c for c in circuits if int(c["circuitNumber"]) % 2 != 0], key=lambda c: c["circuitNumber"])
    evens = sorted([c for c in circuits if int(c["circuitNumber"]) % 2 == 0], key=lambda c: c["circuitNumber"])

    def _walk(col_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        last_desc = ""
        for item in col_list:
            desc = str(item.get("description") or "").strip()
            if desc and ditto_re.match(desc):
                if last_desc:
                    item["description"] = last_desc
            elif desc and desc != "---":
                last_desc = desc
        return col_list

    return _walk(odds) + _walk(evens)


def is_spare_description(desc: str) -> bool:
    upper = clean_upper(desc)
    return upper == "SPARE" or upper.startswith("SPARE ") or " SPARE" in upper


def is_space_description(desc: str) -> bool:
    upper = clean_upper(desc)
    return (
        upper == "SPACE"
        or upper.startswith("SPACE ")
        or upper in {"UNUSED", "BLANK", "OPEN", "EMPTY"}
    )


def estimate_circuit_kva_per_pole(
    breaker_amps: Any,
    description: str,
    load_type: str,
    voltage: str = "120/208V",
) -> Optional[float]:
    """Deterministic ACIES per-pole kVA estimate for field photos when kVA is not listed."""
    desc = clean_upper(description)
    if not desc or is_spare_description(desc) or is_space_description(desc):
        return None

    amps = parse_int_digits(breaker_amps)
    v_ln = line_to_neutral_voltage(voltage)
    breaker_kva = ((amps or 20) * v_ln) / 1000.0

    if any(k in desc for k in ("A/C", "AC ", "AIR COND", "CONDENSER", "HVAC", "RTU", "AHU", "COMPRESSOR", "CHILLER")):
        return round(breaker_kva * 0.70, 2)
    if any(k in desc for k in ("WATER HEATER", "WH", "HWH", "HOT WATER")):
        return round(breaker_kva * 0.60, 2)
    if any(k in desc for k in ("FAN", "EXHAUST", "VENTILAT", "EF-")):
        return round(breaker_kva * 0.50, 2)
    if "ATM" in desc:
        return 0.60
    if any(k in desc for k in ("POLE LIGHT", "POLE LT", "PARKING LOT", "LOT LIGHT")):
        return 1.20
    if any(k in desc for k in ("EXT LIGHT", "EXTERIOR", "OUTSIDE LIGHT", "OUTDOOR LIGHT", "SIGN", "FACADE")):
        return 0.80
    if any(k in desc for k in ("LIGHT", "LTG", "LT ", "LAMP", "EXIT", "NIGHT")):
        if any(k in desc for k in ("LOBBY", "HALL", "OPEN", "COMMON", "CONFERENCE", "WAREHOUSE", "MAIN")):
            return 0.80
        if any(k in desc for k in ("OFFICE", "BREAK", "KITCHEN", "STORAGE")):
            return 0.60
        return 0.40
    if any(k in desc for k in ("RECEP", "RCPT", "PLUG", "DUPLEX", "OUTLET", "REC ", "REC-", "OFFICE", "COUNTER", "CONV")):
        if any(k in desc for k in ("OPEN OFFICE", "HALL", "CORRIDOR", "CONV")):
            return 0.72
        if any(k in desc for k in ("PRIVATE OFFICE", "OFFICE", "CONF", "WORKSTATION", "SYS. FURNITURE", "FURNITURE")):
            return 0.90
        if any(k in desc for k in ("STORAGE", "CLOSET", "MECH", "UTILITY", "REST", "BATH")):
            return 0.36
        return 0.72
    if any(k in desc for k in ("MICROWAVE", "COPIER")):
        return 1.00
    if any(k in desc for k in ("COFFEE", "DISHWASHER")):
        return 1.20
    if any(k in desc for k in ("FRIDGE", "REFRIG")):
        return 0.70
    if any(k in desc for k in ("PRINTER", "TV", "POLYCOM", "FACP", "SONITROL")):
        return 0.50

    l_type = clean_upper(load_type)
    factor = 0.50 if l_type in ("C", "G") else 0.75
    return round(breaker_kva * factor, 2)


def normalize_extracted_panel(raw_panel: Dict[str, Any], fallback_index: int = 1) -> Dict[str, Any]:
    """Normalize a raw extracted panel dict into the canonical Review Studio / Excel structure."""
    panel_name = normalize_panel_name(raw_panel.get("panel_name") or raw_panel.get("panelName"), f"PANEL_{fallback_index}")
    voltage = normalize_voltage(raw_panel.get("voltage")) or "120/208V"
    phase, wire = infer_phase_and_wire(voltage, raw_panel.get("phase"), raw_panel.get("wire"))
    bus_rating = normalize_bus_rating(raw_panel.get("bus_rating") or raw_panel.get("busRating"))
    main_type = clean_upper(raw_panel.get("main_type") or raw_panel.get("mainType"))
    main_breaker_amps = normalize_bus_rating(raw_panel.get("main_breaker_amps") or raw_panel.get("mainBreakerAmps"))
    main_requirement = clean_upper(raw_panel.get("main_requirement") or raw_panel.get("mainRequirement"))
    if not main_requirement:
        main_requirement = format_main_requirement(main_type, main_breaker_amps)
    mounting = normalize_mounting(raw_panel.get("mounting"))
    enclosure = normalize_enclosure(raw_panel.get("enclosure"))
    aic_rating = clean_upper(raw_panel.get("aic_rating") or raw_panel.get("aicRating")) or "EXISTING"
    condition = clean_upper(raw_panel.get("condition"))
    if condition not in VALID_CONDITIONS:
        condition = "EXISTING"
    fed_from = normalize_fed_from(raw_panel.get("fed_from") or raw_panel.get("fedFrom"))
    source_kind = str(raw_panel.get("source_kind") or raw_panel.get("sourceKind") or "as_built_drawing").strip()
    source_indices_raw = raw_panel.get("source_indices")
    if source_indices_raw is None:
        source_indices_raw = raw_panel.get("sourceIndices") or []
    source_indices = sorted({int(i) for i in source_indices_raw if isinstance(i, (int, float)) and int(i) >= 0})

    raw_circuits = raw_panel.get("circuits") or []
    parsed_circuits: List[Dict[str, Any]] = []
    max_ckt_seen = 42
    for entry in raw_circuits:
        if not isinstance(entry, dict):
            continue
        c_num = parse_int_digits(entry.get("circuit_number") if "circuit_number" in entry else entry.get("circuitNumber"))
        if c_num is None or c_num < 1 or c_num > 84:
            continue
        desc = clean_upper(entry.get("description"))
        poles_raw = parse_int_digits(entry.get("poles"))
        amps_raw = parse_int_digits(entry.get("breaker_amps") if "breaker_amps" in entry else entry.get("breakerAmps"))

        space = is_space_description(desc) or (poles_raw == 0 and not amps_raw)
        spare = (not space) and is_spare_description(desc)

        if space:
            poles = 0
            breaker_amps = ""
        else:
            poles = poles_raw if poles_raw in (1, 2, 3) else 1
            breaker_amps = str(amps_raw) if amps_raw else ""

        l_type = clean_upper(entry.get("load_type") if "load_type" in entry else entry.get("loadType"))
        if space or spare or l_type not in VALID_LOAD_TYPES:
            if space or spare:
                l_type = ""
            elif l_type not in VALID_LOAD_TYPES:
                l_type = ""

        note_raw = entry.get("note")
        if note_raw is None:
            note_val = "" if space else "1"
        else:
            note_val = clean_upper(note_raw)
            if space and not note_val:
                note_val = ""

        phase_kva_raw = entry.get("phase_kva") if "phase_kva" in entry else entry.get("phaseKva")
        phase_kva: List[Optional[float]] = []
        if isinstance(phase_kva_raw, (list, tuple)) and len(phase_kva_raw) > 0:
            phase_kva = [normalize_kva_value(v) for v in phase_kva_raw]
        else:
            single_kva = normalize_kva_value(entry.get("kva"))
            if single_kva is not None:
                phase_kva = [single_kva]

        if space or spare:
            phase_kva = []
        elif poles > 1:
            if len(phase_kva) < poles:
                phase_kva.extend([None] * (poles - len(phase_kva)))
            phase_kva = phase_kva[:poles]
        else:
            phase_kva = phase_kva[:1] if phase_kva else [None]

        conf = str(entry.get("confidence") or "high").strip().lower()
        if conf not in VALID_CONFIDENCE:
            conf = "medium"
        review_note = str(entry.get("review_note") if "review_note" in entry else entry.get("reviewNote") or "").strip()

        end_ckt = c_num + (max(poles, 1) - 1) * 2
        if end_ckt > max_ckt_seen:
            max_ckt_seen = end_ckt

        parsed_circuits.append(
            {
                "circuitNumber": c_num,
                "description": desc,
                "breakerAmps": breaker_amps,
                "poles": poles,
                "loadType": l_type,
                "note": note_val,
                "phaseKva": phase_kva,
                "kvaEstimated": bool(entry.get("kvaEstimated", False)),
                "confidence": conf,
                "reviewNote": review_note,
            }
        )

    parsed_circuits = _resolve_ditto_dicts(parsed_circuits)

    # Deduplicate and resolve multi-pole collisions cleanly while flagging issues.
    deduped: Dict[int, Dict[str, Any]] = {}
    for ckt in sorted(parsed_circuits, key=lambda c: c["circuitNumber"]):
        c_num = ckt["circuitNumber"]
        if c_num not in deduped:
            deduped[c_num] = ckt
        else:
            # Prefer non-empty description / higher confidence record.
            existing = deduped[c_num]
            if not existing["description"] and ckt["description"]:
                deduped[c_num] = ckt

    final_circuits: List[Dict[str, Any]] = []
    occupied_slots: set[int] = set()
    validation_warnings: List[str] = list(raw_panel.get("header_warnings") or raw_panel.get("headerWarnings") or [])
    if not bus_rating:
        validation_warnings.append("Bus rating was not clearly readable — please verify.")

    for c_num in sorted(deduped.keys()):
        ckt = deduped[c_num]
        if c_num in occupied_slots:
            validation_warnings.append(f"Circuit {c_num} overlapped a multi-pole breaker above it and was skipped.")
            continue
        poles = int(ckt["poles"] or 0)
        if poles >= 1:
            for offset in range(poles):
                occupied_slots.add(c_num + offset * 2)
        else:
            occupied_slots.add(c_num)

        # Automatic sanity checks -> flag uncertain items for reviewer
        if ckt["description"] and not is_space_description(ckt["description"]) and not is_spare_description(ckt["description"]):
            if not ckt["breakerAmps"]:
                if ckt["confidence"] == "high":
                    ckt["confidence"] = "medium"
                if "amp" not in ckt["reviewNote"].lower():
                    ckt["reviewNote"] = (ckt["reviewNote"] + "; " if ckt["reviewNote"] else "") + "Missing breaker amp rating"
            if not ckt["loadType"]:
                if ckt["confidence"] == "high":
                    ckt["confidence"] = "medium"
                if "load" not in ckt["reviewNote"].lower():
                    ckt["reviewNote"] = (ckt["reviewNote"] + "; " if ckt["reviewNote"] else "") + "Load code (C/D/G/K/M) not assigned"
        final_circuits.append(ckt)

    declared_count = parse_int_digits(raw_panel.get("circuit_count") or raw_panel.get("circuitCount")) or 42
    circuit_count = 84 if max(max_ckt_seen, declared_count) > 42 else 42

    normalized = {
        "id": str(raw_panel.get("id") or f"pnl_{uuid.uuid4().hex[:8]}"),
        "includeInExport": bool(raw_panel.get("includeInExport", True)),
        "panelName": panel_name,
        "sourceKind": source_kind,
        "sourceIndices": source_indices,
        "sourceIds": list(raw_panel.get("sourceIds") or raw_panel.get("source_ids") or []),
        "voltage": voltage,
        "busRating": bus_rating,
        "mainType": main_type,
        "mainBreakerAmps": main_breaker_amps,
        "mainRequirement": main_requirement,
        "phase": phase,
        "wire": wire,
        "mounting": mounting,
        "enclosure": enclosure,
        "aicRating": aic_rating,
        "condition": condition,
        "fedFrom": fed_from,
        "circuitCount": circuit_count,
        "headerWarnings": [str(w).strip() for w in validation_warnings if str(w).strip()],
        "notes": str(raw_panel.get("notes") or "").strip(),
        "circuits": final_circuits,
    }
    normalized["summary"] = compute_panel_load_summary(normalized)
    return normalized


def compute_panel_load_summary(panel: Dict[str, Any]) -> Dict[str, Any]:
    """Compute live Connected Load & NEC Demand Load matching Template.xlsx formulas."""
    phase_totals = {"A": 0.0, "B": 0.0, "C": 0.0}
    cat_totals = {"C": 0.0, "D": 0.0, "G": 0.0, "K": 0.0, "M": 0.0, "ML": 0.0}
    kitchen_count = 0
    flagged_count = 0
    missing_kva_count = 0

    for ckt in panel.get("circuits") or []:
        c_num = parse_int_digits(ckt.get("circuitNumber"))
        if c_num is None or c_num < 1:
            continue
        conf = str(ckt.get("confidence") or "high").lower()
        if conf in ("medium", "low"):
            flagged_count += 1

        desc = clean_upper(ckt.get("description"))
        poles = int(ckt.get("poles") or 0)
        l_type = clean_upper(ckt.get("loadType"))
        phase_kva = ckt.get("phaseKva") or []

        if desc and not is_spare_description(desc) and not is_space_description(desc):
            if not any(normalize_kva_value(v) is not None for v in phase_kva):
                missing_kva_count += 1

        slot_count = max(poles, 1) if poles > 0 else 0
        for idx in range(slot_count):
            row_ckt = c_num + idx * 2
            row_idx_0 = (row_ckt - 1) // 2
            phase_letter = ("A", "B", "C")[row_idx_0 % 3]
            val = normalize_kva_value(phase_kva[idx]) if idx < len(phase_kva) else None
            if val is not None:
                phase_totals[phase_letter] += val
                if l_type in cat_totals:
                    cat_totals[l_type] += val
            if l_type == "K":
                kitchen_count += 1

    connected_total = phase_totals["A"] + phase_totals["B"] + phase_totals["C"]
    # NEC demand factors matching Template.xlsx rows 31..37
    demand_c = cat_totals["C"] * 1.25
    demand_d = cat_totals["D"] * 1.0
    demand_g = (10.0 + (cat_totals["G"] - 10.0) * 0.5) if cat_totals["G"] > 10.0 else cat_totals["G"]
    kitchen_factors = [1.0, 1.0, 0.9, 0.8, 0.7, 0.65]
    k_factor = kitchen_factors[min(6, max(1, kitchen_count)) - 1] if kitchen_count > 0 else 1.0
    demand_k = cat_totals["K"] * k_factor if kitchen_count > 0 else 0.0
    demand_m = cat_totals["M"] * 1.0
    demand_ml = cat_totals["ML"] * 1.25
    demand_total = demand_c + demand_d + demand_g + demand_k + demand_m + demand_ml

    phase_int, _ = infer_phase_and_wire(panel.get("voltage", ""), panel.get("phase"), panel.get("wire"))
    divisor = voltage_amps_divisor(panel.get("voltage", ""), phase_int)
    demand_amps = demand_total / divisor if divisor > 0 else 0.0

    active_phases = [phase_totals["A"], phase_totals["B"]] + ([phase_totals["C"]] if phase_int == 3 else [])
    max_p = max(active_phases) if active_phases else 0.0
    min_p = min(active_phases) if active_phases else 0.0
    imbalance_pct = ((max_p - min_p) / max_p * 100.0) if max_p > 0 else 0.0

    return {
        "phaseA": round(phase_totals["A"], 2),
        "phaseB": round(phase_totals["B"], 2),
        "phaseC": round(phase_totals["C"], 2),
        "connectedTotalKva": round(connected_total, 2),
        "demandTotalKva": round(demand_total, 2),
        "demandAmps": round(demand_amps, 1),
        "imbalancePct": round(imbalance_pct, 1),
        "flaggedCount": flagged_count,
        "missingKvaCount": missing_kva_count,
    }


def apply_estimated_kva_to_panel(panel: Dict[str, Any], overwrite_existing: bool = False) -> Dict[str, Any]:
    """Fill missing kVA values on active circuits with deterministic ACIES estimates."""
    updated = deepcopy(panel)
    voltage = updated.get("voltage") or "120/208V"
    for ckt in updated.get("circuits") or []:
        desc = clean_upper(ckt.get("description"))
        poles = int(ckt.get("poles") or 0)
        if poles <= 0 or not desc or is_spare_description(desc) or is_space_description(desc):
            continue
        existing = ckt.get("phaseKva") or []
        has_any = any(normalize_kva_value(v) is not None for v in existing)
        if has_any and not overwrite_existing:
            continue
        est = estimate_circuit_kva_per_pole(
            ckt.get("breakerAmps"),
            desc,
            ckt.get("loadType", ""),
            voltage=voltage,
        )
        if est is not None:
            ckt["phaseKva"] = [est for _ in range(poles)]
            ckt["kvaEstimated"] = True
    updated["summary"] = compute_panel_load_summary(updated)
    return updated


# ---------------------------------------------------------------------------
# Gemini 4 Hydrogen Prompting & API Call
# ---------------------------------------------------------------------------


def build_hydrogen_extraction_prompt(
    sources: Sequence[Dict[str, Any]],
    mode: str = "auto",
    panel_name_hint: str = "",
) -> str:
    mode_norm = str(mode or "auto").strip().lower()
    hint_clean = clean_upper(panel_name_hint)

    source_lines = []
    for idx, src in enumerate(sources):
        role = str(src.get("role") or "auto")
        label = str(src.get("pageLabel") or src.get("name") or f"Image {idx + 1}")
        hint = str(src.get("hint") or "").strip()
        extra = f" | User note: {hint}" if hint else ""
        source_lines.append(f"- Image {idx}: [{role}] {label}{extra}")
    source_manifest = "\n".join(source_lines) or "- Image 0: [auto]"

    mode_guidance = {
        "as_built_drawing": (
            "MODE: AS-BUILT / RECORD ELECTRICAL DRAWINGS\n"
            "- These images are printed or CAD-plotted panel schedule drawings.\n"
            "- One image/page may contain ONE or MULTIPLE distinct panel schedules (e.g. Panel A, Panel B, Panel C, D1, D2, D3). "
            "Extract EVERY panel schedule visible across the provided pages as separate items in `panels`.\n"
            "- Copy visible kVA / VA values per circuit row verbatim into `phase_kva` (convert VA to kVA, e.g. 900 VA -> '0.9').\n"
            "- NEVER invent or estimate kVA when a cell is blank."
        ),
        "field_photos": (
            "MODE: SITE SURVEY FIELD PHOTOS\n"
            "- These photos show physical panel breakers, handwritten/typed door directories, panel nameplates, and/or main breakers.\n"
            "- Merge split or overlapping photos of the SAME panel into ONE complete panel record (unless the photos clearly show distinct named panels).\n"
            "- Prefer manufacturer nameplate photos for Voltage, Bus Rating, Phase, Wire, AIC, and Enclosure.\n"
            "- Count physical breaker handle ties carefully: 1-pole = 1 slot, 2-pole = 2 vertical slots (e.g. 1 & 3), 3-pole = 3 vertical slots (e.g. 1, 3, 5).\n"
            "- Record `circuit_number` as the TOP-most circuit slot occupied by the breaker.\n"
            "- Leave `phase_kva` empty unless load values are explicitly written on the directory; NEVER guess kVA."
        ),
    }.get(
        mode_norm,
        (
            "MODE: AUTO-DETECT (SITE SURVEY PHOTOS OR AS-BUILT DRAWINGS)\n"
            "- Inspect all images and automatically determine whether they represent printed as-built panel schedules, site survey photos, or a mix.\n"
            "- If a drawing page contains multiple panel schedules, extract ALL of them as separate entries in `panels`.\n"
            "- If multiple field photos show different views/halves of the same panel (breakers + directory + nameplate + main breaker), merge them into ONE panel entry.\n"
            "- Copy visible kVA values verbatim (converting VA to kVA) and NEVER invent or estimate missing kVA."
        ),
    )

    hint_line = (
        f"\nUSER PANEL NAME HINT: '{hint_clean}' (use this if the panel name is not clearly legible in the images; if multiple distinct panels appear on a drawing, use each panel's actual printed name).\n"
        if hint_clean
        else ""
    )

    return f"""
You are an expert electrical project engineer transcribing existing electrical panel schedules into ACIES Engineering's standardized Excel template.

PROVIDED INPUT IMAGES (0-indexed in exact order attached):
{source_manifest}
{hint_line}
{mode_guidance}

EXTRACTION RULES (STRICT):
1. PANEL HEADER:
   - `panel_name`: Short designation only (e.g. "A", "B", "D1", "D3", "LP-1", "MDP"). Do NOT include "(E)" or "PANEL".
   - `voltage`: Standard format such as "120/208V", "277/480V", "120/240V".
   - `bus_rating`: e.g. "100A", "225A", "400A" ("" if not shown).
   - `main_type`: "MLO" or "MCB" ("" if unknown). `main_breaker_amps`: e.g. "200A" if MCB, else "".
   - `phase`: "3" or "1". `wire`: "4" or "3".
   - `mounting`: "SURFACE", "FLUSH", or "RECESSED".
   - `enclosure`: "NEMA 1", "NEMA 3R", etc.
   - `aic_rating`: Exact visible AIC rating (e.g. "10 KAIC", "22,000 AIC", "EXISTING"), or "" if blank. Do not confuse with bus rating or breaker amps.
   - `condition`: "EXISTING" or "NEW" (default "EXISTING" for field surveys / as-builts).
   - `fed_from`: Feeder source if visible (e.g. "FED FROM PANEL 'D2'", "FED FROM MDP", "FED FROM MAIN SERVICE"), else "".
   - `source_indices`: Include the 0-based image indices where this panel appeared.

2. CIRCUITS, MULTI-POLE BREAKERS & CONTINUATION ROWS:
   - Odd circuit numbers (1, 3, 5, ..., 41) are on the LEFT side; even circuit numbers (2, 4, 6, ..., 42) are on the RIGHT side. (Support up to 84 if the panel has 60/84 circuits.)
   - Emit ONE circuit object per breaker, keyed by its TOP-most `circuit_number`.
   - Do NOT emit separate circuit objects for multi-pole continuation rows ("---" or blank rows spanned by a 2-pole or 3-pole breaker). Instead, set `poles` to 2 or 3 on the top circuit and place each occupied row's kVA in `phase_kva` top-to-bottom (e.g. ["7.92", "7.14", "6.14"] for a 3-pole subpanel feeder, or ["2.3", "2.3"] for a 2-pole water heater).
   - Resolve ditto marks (") or "DO" in descriptions.
   - For SPARE breakers (breaker installed, unused): `description="SPARE"`, `poles=1/2/3`, `breaker_amps="20"` (or actual size), `load_type=""`, `note="1"`.
   - For SPACE (no breaker installed / blank slot): `description="SPACE"`, `poles=0`, `breaker_amps=""`, `load_type=""`, `note=""`.
   - Do NOT sum multi-pole phase kVA into one row and do NOT duplicate a total across all poles unless the source schedule actually prints that per-phase value on each row.

3. ACIES LOAD TYPE CODES (`load_type`):
   - `C` = Continuous (lighting, signage, night lights, exit/EM lights, continuous loads)
   - `G` = General receptacle (office/hallway/convenience duplex receptacles)
   - `D` = Dedicated equipment (printers, copiers, appliances, IT/UPS, FACP, water coolers, subpanels, dedicated circuits)
   - `M` = Motor / HVAC (fans, pumps, RTU, AHU, condensers)
   - `ML` = Largest Motor (if specifically designated)
   - `K` = Kitchen equipment
   - Leave `""` for SPARE or SPACE.

4. HONEST CONFIDENCE & UNCERTAINTY FLAGGING:
   - Set `confidence` to `"high"` when clearly legible.
   - Set `confidence` to `"medium"` or `"low"` AND provide a concise `review_note` whenever handwriting is unclear, glare obscures a breaker amp rating, a multi-pole tie is ambiguous, or text is partially cut off.
   - Add any header ambiguities to `header_warnings`.
""".strip()


def _is_retryable_gemini_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "429",
        "resource_exhausted",
        "rate limit",
        "quota",
        "503",
        "unavailable",
        "504",
        "deadline",
        "timeout",
        "timed out",
        "overloaded",
        "temporarily",
    )
    return any(m in text for m in markers)


def _extract_retry_delay(exc: Exception, default_delay: float) -> float:
    text = str(exc)
    m = re.search(r"retry(?:Delay| in)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*s?", text, re.IGNORECASE)
    if m:
        try:
            suggested = float(m.group(1))
            return min(max(suggested, 1.0), 30.0)
        except Exception:
            pass
    return default_delay


def format_hydrogen_error(exc: Exception) -> str:
    msg = str(exc)
    lower = msg.lower()
    if any(k in lower for k in ("api key expired", "api_key_invalid", "invalid api key", "permission_denied")):
        return (
            "Your Google Gemini API key was rejected. Check or regenerate your key in "
            "Google AI Studio, update it in Settings, and try again."
        )
    if "not found" in lower and ("model" in lower or GEMINI_HYDROGEN_MODEL in lower):
        return (
            f"Model '{GEMINI_HYDROGEN_MODEL}' is not accessible with your current API key or region. "
            "Verify your Google AI Studio key has access to Gemini 4 Hydrogen."
        )
    if any(k in lower for k in ("429", "resource_exhausted", "quota", "rate limit")):
        return (
            "Gemini 4 Hydrogen free-tier rate limit reached. Wait 30–60 seconds or analyze fewer "
            "pages per batch, then try again."
        )
    if any(k in lower for k in ("503", "unavailable", "504", "deadline", "timed out", "timeout")):
        return (
            "Gemini 4 Hydrogen timed out or is temporarily busy. Try again in a moment, or "
            "split large drawings into fewer pages per run."
        )
    return msg


def build_structured_field_photo_prompt(
    ordered_sources: Sequence[Dict[str, Any]],
    panel_name: str = "",
    condition: str = "EXISTING",
) -> str:
    """Build a strict single-panel prompt for bucketed site survey photos."""
    clean_name = normalize_panel_name(panel_name, "")
    clean_cond = clean_upper(condition) if clean_upper(condition) in VALID_CONDITIONS else "EXISTING"

    bucket_titles = {
        "nameplate": "PANELBOARD TAGS / FACTORY NAMEPLATES / WIRING & SCCR LABELS",
        "main_breaker": "MAIN BREAKER / MAIN LUGS",
        "breakers": "CIRCUIT BREAKERS (CLOSE-UPS)",
        "directory": "PRINTED / DOOR CIRCUIT DIRECTORY",
        "full_panel": "FULL PANELBOARD / MULTI-PART OVERVIEW (TAG + BREAKERS + DIRECTORY)",
    }
    tag_pretty = {
        "panel_tag": "Panel Name Tag / Placard",
        "nameplate": "Factory Spec Nameplate",
        "wiring_label": "Wiring Diagram / SCCR / UL Label",
        "breakers": "Circuit Breakers",
        "directory": "Circuit Directory",
        "main_breaker": "Main Breaker / MLO",
    }
    grouped_lines: Dict[str, List[str]] = {k: [] for k in bucket_titles}
    other_lines: List[str] = []

    for idx, src in enumerate(ordered_sources):
        role = str(src.get("role") or "breakers").strip().lower()
        label = str(src.get("pageLabel") or src.get("name") or f"Photo {idx + 1}")
        hint = str(src.get("hint") or "").strip()
        detected_tags = [str(t).strip().lower() for t in (src.get("detectedTags") or []) if str(t).strip()]
        pretty_tags = [tag_pretty.get(t, t) for t in detected_tags]
        tags_note = (
            f" | Visible elements: {', '.join(pretty_tags)}"
            if len(pretty_tags) > 1 or any(t in ("panel_tag", "wiring_label") for t in detected_tags)
            else ""
        )
        if role == "breakers":
            coverage = hint or "circuit range not specified; infer only from visible numbering and handle positions"
            line = f"- Image {idx}: {label} | Circuit coverage: {coverage}{tags_note}"
        else:
            extra = f" | Note: {hint}" if hint else ""
            line = f"- Image {idx}: {label}{extra}{tags_note}"
        if role in grouped_lines:
            grouped_lines[role].append(line)
        else:
            other_lines.append(line)

    manifest_sections = []
    for role_key, title in bucket_titles.items():
        entries = grouped_lines[role_key]
        body = "\n".join(entries) if entries else "- (None provided)"
        manifest_sections.append(f"{title}:\n{body}")
    if other_lines:
        manifest_sections.append("ADDITIONAL PHOTOS:\n" + "\n".join(other_lines))
    manifest_text = "\n\n".join(manifest_sections)

    panel_name_rule = (
        f"The user named this panel '{clean_name}'. Use '{clean_name}' as `panel_name` unless a clearly legible nameplate/tag shows a more exact designation (and note any mismatch in `header_warnings`)."
        if clean_name
        else "Determine `panel_name` from the Panelboard Tags / Nameplate or Circuit Directory header (short designation only, e.g. 'A', 'D3', 'LP-1')."
    )

    return f"""
You are an expert electrical project engineer transcribing a SINGLE electrical panel from structured site survey photos into ACIES Engineering's standardized Excel template.

CRITICAL SINGLE-PANEL RULE:
- ALL images attached below belong to ONE SINGLE PANEL.
- Close-up breaker photos may NOT show the panel name — NEVER treat them as a separate panel.
- Merge all split/overlapping views (upper half, middle, bottom half breakers; split directory cards; nameplate tags; main breaker) into ONE complete, deduplicated panel schedule.
- {panel_name_rule}
- Default `condition` to '{clean_cond}' unless clearly marked otherwise.

ATTACHED SITE SURVEY PHOTOS (0-indexed in exact order attached):
{manifest_text}

HOW TO USE EACH PHOTO BUCKET:
1. PANELBOARD TAGS / NAMEPLATE LABELS (primary source for header):
   - Extract `voltage` (e.g. '120/208V', '277/480V', '120/240V'), `bus_rating` (e.g. '225A', '400A'), `phase` ('3' or '1'), `wire` ('4' or '3'), `enclosure` ('NEMA 1', 'NEMA 3R'), `mounting` ('SURFACE', 'FLUSH', 'RECESSED'), `aic_rating` (exact visible AIC/KAIC only; do NOT confuse with bus rating or breaker amps), and `fed_from` (if tagged, e.g. "FED FROM PANEL 'D2'").
   - Prefer legible manufacturer nameplate values over handwritten directory headers if they conflict.
2. MAIN BREAKER / MAIN LUGS (primary source for main device):
   - Set `main_type` to 'MCB' (Main Circuit Breaker) or 'MLO' (Main Lugs Only) when established.
   - Set `main_breaker_amps` to the main breaker handle/nameplate amp rating (e.g. '200A', '225A'); leave '' for MLO or if unreadable.
3. CIRCUIT BREAKERS (authoritative source for physical poles, handle ties, and breaker trip ratings):
   - Treat user-supplied circuit coverage notes as authoritative placement guidance for split/overlapping breaker photos.
   - Count tied handles carefully: 1-pole = 1 slot, 2-pole = 2 vertical slots (e.g. 1 & 3), 3-pole = 3 vertical slots (e.g. 1, 3, 5).
   - Emit ONE circuit object per physical breaker keyed by its TOP-most `circuit_number` (odd = left column, even = right column).
   - Do NOT emit separate entries for spanned continuation rows ('---').
   - Read each breaker handle trip amp rating directly (e.g. '20', '30', '50', '100').
   - Mark installed but unlabeled/spare breakers as SPARE (with actual poles & trip amps, `note='1'`, `load_type=''`). Mark empty knockouts/blanks with no breaker as SPACE (`poles=0`, `breaker_amps=''`, `note=''`).
4. PRINTED / DOOR CIRCUIT DIRECTORY (authoritative source for load descriptions and any printed kVA):
   - Match each directory circuit number to the physical breaker at that circuit slot.
   - Resolve ditto marks (") or 'DO' per column.
   - If kVA or VA values are explicitly printed in the directory, record per-row kVA in `phase_kva` (convert VA -> kVA). If no kVA is shown, leave `phase_kva` empty — NEVER guess or invent kVA.
5. FULL PANELBOARD / MULTI-PART PHOTOS (photos showing combinations like nameplate+breakers, breakers+main, or entire open panel):
   - Extract ALL visible information (header tags, main device, breakers, and door directory) from multi-part / full-panel photos, preferring sharper dedicated close-ups whenever both are provided.

ACIES LOAD TYPE CODES (`load_type`):
- 'C' = Continuous (lighting, signage, night lights, exit/EM lights)
- 'G' = General receptacle (office/hallway/convenience duplex receptacles)
- 'D' = Dedicated equipment (printers, copiers, appliances, IT/UPS, FACP, water coolers, subpanels)
- 'M' = Motor / HVAC (fans, pumps, RTU, AHU, condensers)
- 'ML' = Largest Motor (only if specifically marked)
- 'K' = Kitchen equipment
- '' for SPARE or SPACE.

HONEST CONFIDENCE & UNCERTAINTY FLAGGING:
- Set `confidence` to 'high' when clearly readable.
- Set `confidence` to 'medium' or 'low' and write a concise `review_note` whenever glare, shadows, handwriting, or missing overlap makes a breaker amp rating, pole tie, or description uncertain.
- Record any header uncertainties in `header_warnings`.
""".strip()


def _extract_photo_capture_timestamp(path: Path) -> Tuple[Optional[float], str]:
    """Read EXIF capture timestamp (falling back to file mtime) for chronological sorting."""
    try:
        from datetime import datetime
        from PIL import Image

        _ensure_heif_support()
        with Image.open(path) as raw:
            exif = raw.getexif()
            if exif:
                for tag_id in (36867, 36868, 306):  # DateTimeOriginal, DateTimeDigitized, DateTime
                    val = exif.get(tag_id)
                    if isinstance(val, str) and val.strip():
                        cleaned = val.strip().split("\x00")[0]
                        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                            try:
                                dt = datetime.strptime(cleaned, fmt)
                                return dt.timestamp(), dt.strftime("%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                continue
    except Exception:
        pass
    try:
        from datetime import datetime

        mtime = path.stat().st_mtime
        return mtime, datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None, ""


def _encode_source_for_decision_api(source: Dict[str, Any], max_edge: int = DECISION_SORT_MAX_EDGE) -> str:
    """Return compact JPEG base64 string suitable for fast gemini-decision-1 sorting."""
    path = Path(str(source.get("path") or ""))
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    kind = str(source.get("kind") or "image")
    if kind == "pdf_page":
        page_index = int(source.get("pageIndex") or 0)
        img = _render_pdf_page_to_pil(path, page_index, dpi=110, max_edge=max_edge)
    else:
        img = _open_normalized_pil(path, max_edge)
    try:
        buf = io.BytesIO()
        save_img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
        save_img.save(buf, format="JPEG", quality=76, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    finally:
        try:
            img.close()
        except Exception:
            pass


def _format_decision_api_error(exc: Exception) -> str:
    msg = str(exc)
    lower = msg.lower()
    if any(k in lower for k in ("401", "403", "api_key_invalid", "invalid api key", "permission")):
        return (
            "Google rejected your API key for gemini-decision-1. Check your Google AI Studio key "
            "in Settings and try again."
        )
    if any(k in lower for k in ("429", "resource_exhausted", "rate limit", "quota")):
        return "gemini-decision-1 rate limit reached. Wait a few seconds and try sorting again."
    if any(k in lower for k in ("503", "504", "timeout", "timed out", "unavailable")):
        return "gemini-decision-1 is temporarily busy. Please try again in a moment."
    return f"Auto-sort failed: {msg}"


def sort_survey_photos_with_decision_api(
    sources: Sequence[Dict[str, Any]],
    api_key: str,
    *,
    split_panels: bool = False,
    model: str = GEMINI_DECISION_MODEL,
    url: str = GEMINI_DECISION_URL,
    http_post: Optional[Callable[..., Any]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """Use gemini-decision-1 (/v1beta/decisions) to rapidly auto-bucket site survey photos.

    Evaluates bucket role, breaker coverage section (upper/middle/lower), and optional
    multi-panel boundary splits in a single forward pass per batch (0 output tokens).
    """
    clean_key = str(api_key or "").strip()
    if not clean_key:
        raise RuntimeError(
            "Google Gemini API key is not configured. Add your Google AI Studio key in Settings "
            "(or set GEMINI_API_KEY in .env)."
        )

    source_list = [s for s in (sources or []) if isinstance(s, dict)]
    if not source_list:
        raise ValueError("Add at least one photo to auto-sort.")

    started = time.perf_counter()

    # Enrich with capture timestamps and sort chronologically when splitting across multiple panels.
    enriched = []
    for orig_idx, src in enumerate(source_list):
        p = Path(str(src.get("path") or ""))
        epoch, ts_label = _extract_photo_capture_timestamp(p) if p.exists() else (None, "")
        enriched.append(
            {
                "origIdx": orig_idx,
                "source": src,
                "epoch": epoch if epoch is not None else float(orig_idx),
                "tsLabel": ts_label,
            }
        )

    if split_panels:
        enriched.sort(key=lambda item: (item["epoch"], item["origIdx"]))

    if http_post is None:
        import requests

        http_post = requests.post

    role_criteria = {
        "nameplate": (
            "Manufacturer panelboard nameplate, rating label, engraved panel tag/plaque, "
            "voltage/bus/phase/AIC specification sticker, or 'FED FROM' label."
        ),
        "breakers": (
            "Physical branch circuit breakers inside the panel deadfront (full breaker view "
            "or close-up of breaker handles, amp ratings, and multi-pole handle ties)."
        ),
        "directory": (
            "Printed or handwritten circuit directory card, panel door schedule table, "
            "or printed electrical schedule listing circuit numbers and load descriptions."
        ),
        "main_breaker": (
            "Close-up focused specifically on the main circuit breaker handle/amp rating "
            "or the main lugs (MLO) compartment, separate from the branch breakers."
        ),
        "full_panel": (
            "Wide/full overview photo of an open electrical panelboard showing multiple parts "
            "together in one frame (breakers, door circuit directory, tag/nameplate, and/or main breaker)."
        ),
        "ignore": (
            "Unrelated site photo (room overview, closed panel door with no readable tag, "
            "wall, ceiling, transformer, conduit, meter, or too blurry/dark to use)."
        ),
    }

    section_criteria = {
        "full_panel": "Shows the entire or nearly entire column(s) of branch breakers in one shot.",
        "upper_half": "Close-up of the top / upper portion of the branch breakers.",
        "middle_section": "Close-up of the middle portion of the branch breakers.",
        "lower_half": "Close-up of the bottom / lower portion of the branch breakers.",
        "not_applicable": "Not a close-up or view of physical branch circuit breakers.",
    }

    assignments_by_pos: Dict[int, Dict[str, Any]] = {}
    batch_size = max(2, DECISION_SORT_BATCH_SIZE)
    step = (batch_size - 1) if split_panels else batch_size
    pos = 0

    while pos < len(enriched):
        chunk = enriched[pos : pos + batch_size]
        input_parts: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Electrical site survey photos to classify into panel schedule upload buckets. "
                    "Photos are numbered Photo 0 through Photo "
                    f"{len(chunk) - 1} in chronological capture order."
                ),
            }
        ]
        questions: Dict[str, Any] = {}

        for local_idx, item in enumerate(chunk):
            src = item["source"]
            name = str(src.get("pageLabel") or src.get("name") or f"Photo {local_idx + 1}")
            ts_note = f", captured {item['tsLabel']}" if item["tsLabel"] else ""
            gap_parts = []
            non_panel_gap = int(src.get("nonPanelGapBefore") or 0)
            gap_sec = int(src.get("gapSecondsBefore") or 0)
            if non_panel_gap > 0:
                gap_parts.append(f"{non_panel_gap} non-panel site photo{'s' if non_panel_gap != 1 else ''}")
            if gap_sec >= 20:
                mins, secs = divmod(gap_sec, 60)
                gap_parts.append(f"{mins}m {secs}s" if mins else f"{secs}s")
            gap_note = f" [after {' & '.join(gap_parts)} since previous panel photo]" if gap_parts else ""
            input_parts.append(
                {
                    "type": "text",
                    "text": f"Photo {local_idx}: {name}{ts_note}{gap_note}",
                }
            )
            b64_jpeg = _encode_source_for_decision_api(src, max_edge=DECISION_SORT_MAX_EDGE)
            input_parts.append(
                {
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "data": b64_jpeg,
                    "resolution": "low",
                }
            )

            global_pos = pos + local_idx
            # When overlapping 1 photo between chunks for split detection, only re-ask split on local_idx >= 1.
            if global_pos not in assignments_by_pos:
                questions[f"role_{local_idx}"] = {
                    "type": "choice",
                    "instructions": f"Which upload bucket does Photo {local_idx} belong to?",
                    "criteria": role_criteria,
                }
                questions[f"section_{local_idx}"] = {
                    "type": "choice",
                    "instructions": (
                        f"If Photo {local_idx} shows physical branch circuit breakers, "
                        "which vertical portion of the panel does it cover?"
                    ),
                    "criteria": section_criteria,
                }
            if split_panels and local_idx > 0:
                questions[f"split_{local_idx}"] = {
                    "type": "noul",
                    "instructions": (
                        f"Compare Photo {local_idx} to Photo {local_idx - 1}. Considering visible "
                        "panel designations/tags, enclosure/deadfront style, breaker brand/layout, "
                        "directory format, and capture timestamp gap, does Photo "
                        f"{local_idx} start a DIFFERENT electrical panel than Photo {local_idx - 1}?"
                    ),
                }

        payload = {
            "model": model,
            "input": input_parts,
            "questions": questions,
        }

        last_exc: Optional[Exception] = None
        response_json: Optional[Dict[str, Any]] = None
        for attempt in range(3):
            try:
                resp = http_post(
                    url,
                    headers={
                        "x-goog-api-key": clean_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=(5, 45),
                    allow_redirects=False,
                )
                resp.raise_for_status()
                response_json = resp.json()
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and _is_retryable_gemini_error(exc):
                    sleep_fn(_extract_retry_delay(exc, 1.5 * (attempt + 1)))
                    continue
                raise RuntimeError(_format_decision_api_error(exc)) from exc

        if not isinstance(response_json, dict) or not isinstance(response_json.get("answers"), dict):
            raise RuntimeError(
                _format_decision_api_error(last_exc or RuntimeError("Unexpected empty response from Decisions API."))
            )

        answers = response_json["answers"]
        for local_idx, item in enumerate(chunk):
            global_pos = pos + local_idx
            src = item["source"]
            if global_pos not in assignments_by_pos:
                role_ans = answers.get(f"role_{local_idx}") or {}
                bucket = str(role_ans.get("choice") or "breakers").strip().lower()
                if bucket not in DECISION_VALID_BUCKETS:
                    bucket = "breakers"
                raw_conf = role_ans.get("confidence")
                conf = float(raw_conf) if isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool) else 0.5

                sec_ans = answers.get(f"section_{local_idx}") or {}
                sec_choice = str(sec_ans.get("choice") or "not_applicable").strip().lower()
                sec_conf = sec_ans.get("confidence")
                sec_conf_f = float(sec_conf) if isinstance(sec_conf, (int, float)) and not isinstance(sec_conf, bool) else 0.0
                suggested_hint = ""
                if bucket == "breakers" and sec_choice in DECISION_SECTION_HINTS and sec_conf_f >= 0.65:
                    suggested_hint = DECISION_SECTION_HINTS[sec_choice]

                assignments_by_pos[global_pos] = {
                    "id": str(src.get("id") or ""),
                    "bucket": bucket,
                    "confidence": round(conf, 3),
                    "lowConfidence": conf < DECISION_LOW_CONFIDENCE_THRESHOLD,
                    "suggestedHint": suggested_hint,
                    "capturedAt": item["tsLabel"],
                    "splitProbability": 0.0,
                    "panelGroupIndex": 0,
                }

            if split_panels and local_idx > 0:
                split_ans = answers.get(f"split_{local_idx}") or {}
                raw_prob = split_ans.get("probability")
                prob = float(raw_prob) if isinstance(raw_prob, (int, float)) and not isinstance(raw_prob, bool) else 0.0
                assignments_by_pos[global_pos]["splitProbability"] = round(prob, 3)

        if pos + batch_size >= len(enriched):
            break
        pos += step

    ordered_assignments = [assignments_by_pos[i] for i in range(len(enriched))]

    # Assign panel group indices cleanly when split_panels is enabled.
    current_group = 0
    if split_panels:
        for i, entry in enumerate(ordered_assignments):
            if i > 0 and entry["bucket"] != "ignore" and entry["splitProbability"] >= DECISION_PANEL_SPLIT_THRESHOLD:
                current_group += 1
            entry["panelGroupIndex"] = current_group

    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    return {
        "model": model,
        "elapsedMs": elapsed_ms,
        "splitPanels": bool(split_panels),
        "panelGroupCount": (current_group + 1) if split_panels else 1,
        "assignments": ordered_assignments,
    }


def _invoke_hydrogen_with_retries(
    client,
    *,
    model: str,
    prompt: str,
    pil_images: Sequence[Any],
    schema_cls,
    sleep_fn: Callable[[float], None] = time.sleep,
):
    from google.genai import types

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema_cls,
        temperature=0.1,
    )

    last_exc: Optional[Exception] = None
    response = None
    max_attempts = len(STUDIO_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(max_attempts):
        try:
            logger.info(
                "Panel Schedule Studio analyzing %d image(s) with %s (attempt %d/%d)",
                len(pil_images),
                model,
                attempt + 1,
                max_attempts,
            )
            response = client.models.generate_content(
                model=model,
                contents=[prompt, *pil_images],
                config=config,
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt < len(STUDIO_RETRY_DELAYS_SECONDS) and _is_retryable_gemini_error(exc):
                delay = _extract_retry_delay(exc, STUDIO_RETRY_DELAYS_SECONDS[attempt])
                logger.warning(
                    "Gemini 4 Hydrogen transient error on attempt %d: %s (retrying in %.1fs)",
                    attempt + 1,
                    exc,
                    delay,
                )
                sleep_fn(delay)
                continue
            raise RuntimeError(format_hydrogen_error(exc)) from exc

    if response is None:
        raise RuntimeError(format_hydrogen_error(last_exc or RuntimeError("No response from Gemini.")))

    parsed = getattr(response, "parsed", None)
    if parsed is None:
        raw_text = (getattr(response, "text", None) or "").strip()
        if not raw_text:
            raise RuntimeError("Gemini 4 Hydrogen returned an empty response. Please try again.")
        raw_data = json.loads(raw_text)
        if hasattr(schema_cls, "model_validate"):
            parsed = schema_cls.model_validate(raw_data)
        else:
            parsed = schema_cls.parse_obj(raw_data)
    return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()


def analyze_panel_groups_with_hydrogen(
    groups: Sequence[Dict[str, Any]],
    api_key: str,
    *,
    model: str = GEMINI_HYDROGEN_MODEL,
    client_factory: Optional[Callable[[str], Any]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Analyze one or more structured panel groups (field-photo panels and/or as-built PDF sets)."""
    clean_key = str(api_key or "").strip()
    if not clean_key:
        raise RuntimeError(
            "Google Gemini API key is not configured. Add your free Google AI Studio key in Settings "
            "(or set GEMINI_API_KEY in .env)."
        )

    valid_groups = [
        g for g in (groups or [])
        if isinstance(g, dict) and any(s.get("selected", True) for s in (g.get("sources") or []))
    ]
    if not valid_groups:
        raise ValueError("Add at least one panel group with photos or PDF pages to analyze.")

    from google import genai
    from google.genai import types

    if client_factory is not None:
        client = client_factory(clean_key)
    else:
        client = genai.Client(
            api_key=clean_key,
            http_options=types.HttpOptions(timeout=STUDIO_REQUEST_TIMEOUT_MS),
        )

    all_panels: List[Dict[str, Any]] = []
    viewer_urls: Dict[str, str] = {}
    overall_notes_parts: List[str] = []
    bucket_order = {"nameplate": 0, "main_breaker": 1, "breakers": 2, "directory": 3, "full_panel": 4}
    total_groups = len(valid_groups)

    def _emit_progress(progress_pct: int, message: str, current_idx: int) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(
                {
                    "progress": max(0, min(100, int(progress_pct))),
                    "message": message,
                    "currentGroup": current_idx,
                    "totalGroups": total_groups,
                }
            )
        except Exception:
            pass

    for group_idx, group in enumerate(valid_groups, start=1):
        mode = str(group.get("mode") or "field_photos").strip().lower()
        selected_sources = [s for s in (group.get("sources") or []) if s.get("selected", True)]
        if not selected_sources:
            continue

        group_label = (
            f"Panel {normalize_panel_name(group.get('panelName'), str(group_idx))}"
            if mode == "field_photos"
            else f"Drawing batch {group_idx}"
        )
        base_pct = int(12 + ((group_idx - 1) / max(total_groups, 1)) * 78)
        _emit_progress(
            base_pct,
            f"Analyzing {group_label} ({group_idx}/{total_groups}, {len(selected_sources)} image{'s' if len(selected_sources) != 1 else ''}) with Gemini 4 Hydrogen...",
            group_idx,
        )

        if mode == "field_photos":
            ordered_sources = sorted(
                selected_sources,
                key=lambda s: bucket_order.get(str(s.get("role") or "").lower(), 99),
            )
        else:
            ordered_sources = list(selected_sources)

        pil_images = []
        try:
            for src in ordered_sources:
                pil_images.append(_open_source_for_analysis(src))
                src_id = str(src.get("id") or "")
                if src_id and not src.get("viewerDataUrl"):
                    try:
                        viewer_urls[src_id] = render_source_viewer_image(src)
                    except Exception:
                        pass

            if mode == "field_photos":
                user_panel_name = normalize_panel_name(group.get("panelName"), "")
                user_condition = clean_upper(group.get("condition")) or "EXISTING"
                prompt = build_structured_field_photo_prompt(
                    ordered_sources,
                    panel_name=user_panel_name,
                    condition=user_condition,
                )
                raw_panel = _invoke_hydrogen_with_retries(
                    client,
                    model=model,
                    prompt=prompt,
                    pil_images=pil_images,
                    schema_cls=ExtractedPanelSchema,
                    sleep_fn=sleep_fn,
                )
                # Always respect the user's explicit panel name if provided; never allow unnamed close-ups to drift.
                if user_panel_name:
                    raw_panel["panel_name"] = user_panel_name
                if user_condition in VALID_CONDITIONS and not raw_panel.get("condition"):
                    raw_panel["condition"] = user_condition
                raw_panel["source_kind"] = "field_photos"
                norm = normalize_extracted_panel(raw_panel, fallback_index=len(all_panels) + 1)
                norm["sourceIndices"] = list(range(len(ordered_sources)))
                norm["sourceIds"] = [str(s.get("id") or "") for s in ordered_sources if s.get("id")]
                all_panels.append(norm)
            else:
                panel_name_hint = str(group.get("panelName") or group.get("panelNameHint") or "")
                prompt = build_hydrogen_extraction_prompt(
                    ordered_sources,
                    mode="as_built_drawing",
                    panel_name_hint=panel_name_hint,
                )
                batch_dict = _invoke_hydrogen_with_retries(
                    client,
                    model=model,
                    prompt=prompt,
                    pil_images=pil_images,
                    schema_cls=ExtractedPanelBatchSchema,
                    sleep_fn=sleep_fn,
                )
                raw_panels = batch_dict.get("panels") or []
                if batch_dict.get("overall_notes"):
                    overall_notes_parts.append(str(batch_dict["overall_notes"]).strip())
                for raw_panel in raw_panels:
                    norm = normalize_extracted_panel(raw_panel, fallback_index=len(all_panels) + 1)
                    valid_indices = [i for i in norm["sourceIndices"] if 0 <= i < len(ordered_sources)]
                    if not valid_indices:
                        valid_indices = [0]
                    norm["sourceIndices"] = valid_indices
                    norm["sourceIds"] = [
                        str(ordered_sources[i].get("id") or "")
                        for i in valid_indices
                        if ordered_sources[i].get("id")
                    ]
                    all_panels.append(norm)
        finally:
            for img in pil_images:
                try:
                    img.close()
                except Exception:
                    pass

    if not all_panels:
        raise RuntimeError(
            "No panel schedules were detected in the uploaded photos or PDF pages. "
            "Check that at least one panel has photos/pages attached."
        )

    return {
        "model": model,
        "overallNotes": " ".join(overall_notes_parts).strip(),
        "panels": all_panels,
        "viewerUrls": viewer_urls,
    }


def analyze_sources_with_hydrogen(
    sources: Sequence[Dict[str, Any]],
    api_key: str,
    *,
    mode: str = "auto",
    panel_name_hint: str = "",
    model: str = GEMINI_HYDROGEN_MODEL,
    client_factory: Optional[Callable[[str], Any]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """Run multimodal panel schedule extraction using Gemini 4 Hydrogen."""
    clean_key = str(api_key or "").strip()
    if not clean_key:
        raise RuntimeError(
            "Google Gemini API key is not configured. Add your free Google AI Studio key in Settings "
            "(or set GEMINI_API_KEY in .env)."
        )

    selected_sources = [s for s in (sources or []) if s.get("selected", True)]
    if not selected_sources:
        raise ValueError("Select at least one photo or PDF page to analyze.")

    from google import genai
    from google.genai import types

    if client_factory is not None:
        client = client_factory(clean_key)
    else:
        client = genai.Client(
            api_key=clean_key,
            http_options=types.HttpOptions(timeout=STUDIO_REQUEST_TIMEOUT_MS),
        )

    mode_norm = str(mode or "auto").strip().lower()
    if mode_norm == "field_photos":
        return analyze_panel_groups_with_hydrogen(
            [{"mode": "field_photos", "panelName": panel_name_hint, "sources": selected_sources}],
            clean_key,
            model=model,
            client_factory=lambda _k: client,
            sleep_fn=sleep_fn,
        )

    prompt = build_hydrogen_extraction_prompt(
        selected_sources,
        mode=mode,
        panel_name_hint=panel_name_hint,
    )

    pil_images = []
    viewer_urls: Dict[str, str] = {}
    try:
        for src in selected_sources:
            pil_images.append(_open_source_for_analysis(src))
            src_id = str(src.get("id") or "")
            if src_id and not src.get("viewerDataUrl"):
                try:
                    viewer_urls[src_id] = render_source_viewer_image(src)
                except Exception:
                    pass

        batch_dict = _invoke_hydrogen_with_retries(
            client,
            model=model,
            prompt=prompt,
            pil_images=pil_images,
            schema_cls=ExtractedPanelBatchSchema,
            sleep_fn=sleep_fn,
        )
    finally:
        for img in pil_images:
            try:
                img.close()
            except Exception:
                pass

    raw_panels = batch_dict.get("panels") or []
    if not raw_panels:
        raise RuntimeError(
            "No panel schedules were detected in the selected images. "
            "Check that the selected pages/photos clearly show a panel schedule or circuit directory."
        )

    normalized_panels = []
    for idx, raw_panel in enumerate(raw_panels, start=1):
        norm = normalize_extracted_panel(raw_panel, fallback_index=idx)
        norm["sourceIndices"] = [i for i in norm["sourceIndices"] if 0 <= i < len(selected_sources)]
        if not norm["sourceIndices"]:
            norm["sourceIndices"] = [0]
        norm["sourceIds"] = [
            str(selected_sources[i].get("id") or "")
            for i in norm["sourceIndices"]
            if selected_sources[i].get("id")
        ]
        normalized_panels.append(norm)

    return {
        "model": model,
        "overallNotes": str(batch_dict.get("overall_notes") or "").strip(),
        "panels": normalized_panels,
        "viewerUrls": viewer_urls,
        "analyzedSourceIds": [str(s.get("id") or "") for s in selected_sources],
    }


# ---------------------------------------------------------------------------
# ACIES Excel Template Writer (.xlsx + .xls via Excel COM)
# ---------------------------------------------------------------------------


def _make_unique_sheet_name(raw_name: str, existing_names: Iterable[str]) -> str:
    existing = set(existing_names)
    base = re.sub(r'[:\\/?*\[\]]+', "-", clean_upper(raw_name) or "PANEL").strip(" '")
    base = base[:31] or "PANEL"
    if base not in existing:
        return base
    suffix = 2
    while True:
        suffix_str = f" ({suffix})"
        candidate = f"{base[: max(1, 31 - len(suffix_str))]}{suffix_str}"
        if candidate not in existing:
            return candidate
        suffix += 1


def _split_fed_from_lines(fed_from: str) -> Tuple[str, str]:
    text = clean_upper(fed_from)
    if not text:
        return "", ""
    if len(text) <= 22:
        return text, ""
    words = text.split(" ")
    line1_parts: List[str] = []
    line2_parts: List[str] = []
    for word in words:
        candidate = " ".join(line1_parts + [word])
        if len(candidate) <= 22 or not line1_parts:
            line1_parts.append(word)
        else:
            line2_parts.append(word)
    return " ".join(line1_parts), " ".join(line2_parts)


def _populate_template_sheet(
    ws,
    panel: Dict[str, Any],
    *,
    circuit_offset: int = 0,
    section_suffix: str = "",
) -> None:
    """Write one normalized panel (or 43-84 continuation section) onto a copied TEMPLATE sheet."""
    panel_name = normalize_panel_name(panel.get("panelName"), "PANEL")
    condition = clean_upper(panel.get("condition"))
    cond_code = "N" if condition == "NEW" else "E"
    title_suffix = f" {section_suffix}" if section_suffix else ""
    ws["A3"] = f'({cond_code}) PANEL "{panel_name}"{title_suffix}\n\n'

    voltage = normalize_voltage(panel.get("voltage")) or "120/208V"
    phase_int, wire_int = infer_phase_and_wire(voltage, panel.get("phase"), panel.get("wire"))
    bus_rating = normalize_bus_rating(panel.get("busRating"))
    main_req = clean_upper(panel.get("mainRequirement")) or format_main_requirement(
        panel.get("mainType", ""),
        panel.get("mainBreakerAmps", ""),
    )
    mounting = normalize_mounting(panel.get("mounting"))
    enclosure = normalize_enclosure(panel.get("enclosure"))
    aic_rating = clean_upper(panel.get("aicRating")) or "EXISTING"
    cond_label = "NEW" if cond_code == "N" else "EXISTING"
    fed_line1, fed_line2 = _split_fed_from_lines(panel.get("fedFrom", ""))

    ws["G2"] = voltage
    ws["G3"] = bus_rating
    ws["G4"] = f" {main_req}" if main_req == "MLO" else main_req
    ws["K2"] = wire_int
    ws["K3"] = phase_int
    ws["K4"] = enclosure
    ws["N2"] = mounting
    ws["N3"] = aic_rating
    ws["N4"] = cond_label
    ws["P3"] = fed_line1
    ws["P4"] = fed_line2

    # Update voltage-aware Amps formula in Q38 so 277/480V and 120/240V compute accurately.
    divisor = voltage_amps_divisor(voltage, phase_int)
    ws["Q38"] = f"=Q37/{divisor:g}"

    # Clear circuit data cells (rows 8..28) and update circuit numbers for continuation sheets.
    for row_idx in range(START_ROW, MAX_ROW + 1):
        slot_index = row_idx - START_ROW
        ws[f"A{row_idx}"] = circuit_offset + slot_index * 2 + 1
        ws[f"S{row_idx}"] = circuit_offset + slot_index * 2 + 2
        ws[f"{COL_PHASE}{row_idx}"] = ("A", "B", "C")[slot_index % 3]
        for col in (
            COL_L_NOTE,
            COL_L_TYPE,
            COL_L_POLE,
            COL_L_TRIP,
            COL_L_DESC,
            COL_L_KVA,
            COL_R_KVA,
            COL_R_DESC,
            COL_R_POLE,
            COL_R_TRIP,
            COL_R_TYPE,
            COL_R_NOTE,
        ):
            ws[f"{col}{row_idx}"] = None

    min_ckt = circuit_offset + 1
    max_ckt = circuit_offset + SLOTS_PER_SHEET
    occupied: set[Tuple[str, int]] = set()

    circuits = sorted(panel.get("circuits") or [], key=lambda c: int(c.get("circuitNumber") or 0))
    for ckt in circuits:
        c_num = parse_int_digits(ckt.get("circuitNumber"))
        if c_num is None or c_num < min_ckt or c_num > max_ckt:
            continue

        rel_ckt = c_num - circuit_offset
        row_idx = START_ROW + math.ceil(rel_ckt / 2) - 1
        if row_idx < START_ROW or row_idx > MAX_ROW:
            continue

        is_odd = (c_num % 2 != 0)
        side = "L" if is_odd else "R"
        if (side, row_idx) in occupied:
            continue

        if is_odd:
            c_note, c_type, c_pole, c_trip, c_desc, c_kva = (
                COL_L_NOTE,
                COL_L_TYPE,
                COL_L_POLE,
                COL_L_TRIP,
                COL_L_DESC,
                COL_L_KVA,
            )
        else:
            c_note, c_type, c_pole, c_trip, c_desc, c_kva = (
                COL_R_NOTE,
                COL_R_TYPE,
                COL_R_POLE,
                COL_R_TRIP,
                COL_R_DESC,
                COL_R_KVA,
            )

        desc = clean_upper(ckt.get("description"))
        poles = int(ckt.get("poles") or 0)
        trip_int = parse_int_digits(ckt.get("breakerAmps"))
        space = poles <= 0 or is_space_description(desc)
        spare = (not space) and is_spare_description(desc)

        note_val = clean_upper(ckt.get("note"))
        if space:
            ws[f"{c_desc}{row_idx}"] = desc or "SPACE"
            ws[f"{c_note}{row_idx}"] = note_val or None
            occupied.add((side, row_idx))
            continue

        l_type = "" if spare else clean_upper(ckt.get("loadType"))
        if l_type not in VALID_LOAD_TYPES:
            l_type = ""
        phase_kva = ckt.get("phaseKva") or []
        first_kva = None if spare else (normalize_kva_value(phase_kva[0]) if len(phase_kva) > 0 else None)

        ws[f"{c_desc}{row_idx}"] = desc
        ws[f"{c_pole}{row_idx}"] = poles
        ws[f"{c_trip}{row_idx}"] = trip_int if trip_int is not None else (clean_upper(ckt.get("breakerAmps")) or None)
        ws[f"{c_kva}{row_idx}"] = first_kva
        ws[f"{c_type}{row_idx}"] = l_type or None
        ws[f"{c_note}{row_idx}"] = note_val or ("1" if (desc or trip_int) else None)
        occupied.add((side, row_idx))

        if poles > 1:
            for offset in range(1, poles):
                ext_row = row_idx + offset
                if ext_row > MAX_ROW:
                    break
                ext_kva = None if spare else (normalize_kva_value(phase_kva[offset]) if offset < len(phase_kva) else None)
                ws[f"{c_desc}{ext_row}"] = "---"
                ws[f"{c_pole}{ext_row}"] = "-"
                ws[f"{c_trip}{ext_row}"] = "-"
                ws[f"{c_kva}{ext_row}"] = ext_kva
                ws[f"{c_type}{ext_row}"] = l_type or None
                ws[f"{c_note}{ext_row}"] = note_val or ("1" if (desc or trip_int) else None)
                occupied.add((side, ext_row))


def _ensure_template_worksheet(wb, template_path: Path):
    if "TEMPLATE" in wb.sheetnames:
        return wb["TEMPLATE"]
    if not template_path.exists():
        raise FileNotFoundError(f"Panel schedule template not found: {template_path}")
    import openpyxl
    from openpyxl.worksheet.copier import WorksheetCopy

    template_wb = openpyxl.load_workbook(template_path)
    try:
        src = template_wb["TEMPLATE"] if "TEMPLATE" in template_wb.sheetnames else template_wb.active
        dst = wb.create_sheet("TEMPLATE")
        WorksheetCopy(src, dst).copy_worksheet()
        return dst
    finally:
        template_wb.close()


def _write_panels_to_xlsx(
    panels: Sequence[Dict[str, Any]],
    xlsx_path: Path,
    template_path: Path,
    *,
    mode: str = "new",
    replace_existing_sheets: bool = False,
) -> List[str]:
    import openpyxl

    if mode == "new" or not xlsx_path.exists():
        if not template_path.exists():
            raise FileNotFoundError(f"Panel schedule template not found: {template_path}")
        wb = openpyxl.load_workbook(template_path)
        if "TEMPLATE" not in wb.sheetnames:
            wb.active.title = "TEMPLATE"
        # Cleanly start from JUST the TEMPLATE sheet when creating a brand-new workbook.
        for sheet_name in list(wb.sheetnames):
            if sheet_name != "TEMPLATE":
                del wb[sheet_name]
    else:
        wb = openpyxl.load_workbook(xlsx_path)
        _ensure_template_worksheet(wb, template_path)

    template_ws = wb["TEMPLATE"]
    created_sheets: List[str] = []

    for raw_panel in panels:
        if not raw_panel.get("includeInExport", True):
            continue
        panel = normalize_extracted_panel(raw_panel)
        has_upper_section = any(
            (parse_int_digits(c.get("circuitNumber")) or 0) > SLOTS_PER_SHEET
            for c in panel.get("circuits") or []
        )
        sections = (
            [(0, "(1-42)"), (SLOTS_PER_SHEET, "(43-84)")]
            if has_upper_section
            else [(0, "")]
        )
        for offset, suffix in sections:
            desired = panel["panelName"] if not suffix else f"{panel['panelName']} {suffix}"
            clean_desired = re.sub(r'[:\\/?*\[\]]+', "-", clean_upper(desired) or "PANEL").strip(" '")[:31]
            if replace_existing_sheets and clean_desired in wb.sheetnames and clean_desired != "TEMPLATE":
                del wb[clean_desired]
                sheet_name = clean_desired
            else:
                sheet_name = _make_unique_sheet_name(desired, wb.sheetnames)
            target = wb.copy_worksheet(template_ws)
            target.title = sheet_name
            target.sheet_view.showGridLines = False
            _populate_template_sheet(target, panel, circuit_offset=offset, section_suffix=suffix)
            created_sheets.append(sheet_name)

    if not created_sheets:
        raise ValueError("No panels are selected for export.")

    # Place TEMPLATE at the end so the first exported panel opens immediately in Excel.
    if "TEMPLATE" in wb.sheetnames and len(wb.sheetnames) > 1:
        tmpl = wb["TEMPLATE"]
        wb._sheets.remove(tmpl)
        wb._sheets.append(tmpl)
        wb.active = 0

    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = xlsx_path.with_name(f".{xlsx_path.stem}_{uuid.uuid4().hex[:8]}.tmp.xlsx")
    try:
        wb.save(tmp_path)
        wb.close()
        os.replace(tmp_path, xlsx_path)
    except PermissionError as exc:
        raise RuntimeError(
            f"Cannot overwrite '{xlsx_path.name}' because it is open in Excel or locked. "
            "Close the file in Excel (or choose a different filename) and click Export again."
        ) from exc
    except OSError as exc:
        if getattr(exc, "winerror", None) in (5, 32, 33) or getattr(exc, "errno", None) == 13:
            raise RuntimeError(
                f"Cannot overwrite '{xlsx_path.name}' because it is open in Excel or locked. "
                "Close the file in Excel (or choose a different filename) and click Export again."
            ) from exc
        raise
    finally:
        try:
            wb.close()
        except Exception:
            pass
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

    return created_sheets


def export_panels_to_excel(
    panels: Sequence[Dict[str, Any]],
    output_path: str,
    template_path: Path,
    *,
    mode: str = "new",
    replace_existing_sheets: bool = False,
    excel_converter: Optional[Callable[[str, str, str], None]] = None,
) -> Dict[str, Any]:
    """Export reviewed panels to .xlsx or legacy .xls while preserving formulas & formatting."""
    dest = Path(str(output_path or "").strip())
    if not str(dest):
        raise ValueError("Choose an output Excel file path.")
    ext = dest.suffix.lower()
    if ext not in (".xlsx", ".xls"):
        raise ValueError("Output file must end with .xlsx or .xls.")

    if mode == "existing" and not dest.exists():
        raise FileNotFoundError(f"Existing workbook not found: {dest}")

    # Create a safety backup when modifying an existing workbook in place.
    backup_path: Optional[Path] = None
    if mode == "existing" and dest.exists():
        backup_dir = dest.parent / ".panel_ai_backups"
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"{dest.stem}_{stamp}{dest.suffix}"
            shutil.copy2(dest, backup_path)
        except Exception as exc:
            logger.warning("Could not create pre-export backup for %s: %s", dest, exc)
            backup_path = None

    if ext == ".xlsx":
        sheets = _write_panels_to_xlsx(
            panels,
            dest,
            template_path,
            mode=mode,
            replace_existing_sheets=replace_existing_sheets,
        )
        return {
            "path": str(dest),
            "sheets": sheets,
            "backupPath": str(backup_path) if backup_path else "",
        }

    # Legacy .xls path: round-trip through temporary .xlsx via Excel COM.
    if excel_converter is None:
        raise RuntimeError("Exporting to .xls requires Microsoft Excel COM conversion.")

    tmp_dir = Path(tempfile.mkdtemp(prefix="acies_panel_xls_"))
    tmp_xlsx = tmp_dir / f"{dest.stem}.xlsx"
    try:
        if mode == "existing":
            excel_converter(str(dest), str(tmp_xlsx), ".xlsx")
        sheets = _write_panels_to_xlsx(
            panels,
            tmp_xlsx,
            template_path,
            mode=mode,
            replace_existing_sheets=replace_existing_sheets,
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        excel_converter(str(tmp_xlsx), str(dest), ".xls")
        return {
            "path": str(dest),
            "sheets": sheets,
            "backupPath": str(backup_path) if backup_path else "",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
