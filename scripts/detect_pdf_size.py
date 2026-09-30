# --- detect_pdf_size.py ---
# Detects the paper size of PDF files in a project's PDF folder
# Returns the matching paper size name for the PlotDWGs.ps1 script

import sys
import os
import time
import heapq
import json
try:
    # PlotDWGs.ps1 reads this script's stdout as the paper size, and importing PyMuPDF
    # under its old "fitz" name now prints a deprecation warning there.
    import pymupdf as fitz
except ImportError:  # PyMuPDF older than 1.24.3
    import fitz


# Standard paper sizes in points (1 inch = 72 points)
# Using tolerance-based matching to account for slight variations
PAPER_SIZES = {
    "ANSI full bleed D (22.00 x 34.00 Inches)": (22 * 72, 34 * 72),   # 1584 x 2448
    "ARCH full bleed D (24.00 x 36.00 Inches)": (24 * 72, 36 * 72),   # 1728 x 2592
    "ARCH full bleed E1 (30.00 x 42.00 Inches)": (30 * 72, 42 * 72),  # 2160 x 3024
    "ARCH full bleed E (36.00 x 48.00 Inches)": (36 * 72, 48 * 72),   # 2592 x 3456
}

# Tolerance in points (0.5 inch = 36 points)
TOLERANCE = 36

# Performance guards to keep detection fast
MAX_CANDIDATE_PDFS = 25
MAX_SCAN_SECONDS = 4.0
MAX_PDF_BYTES = 150 * 1024 * 1024


def get_project_root(dwg_path):
    r"""
    Given a DWG file path, find the project root folder.
    Project structure: \\acies.lan\cachedrive\Projects\Nelson\BAC\2025\250368 ProjectName\Electrical\file.dwg
    Project root is the folder with the project number (e.g., "250368 ProjectName")
    """
    path = os.path.normpath(dwg_path)

    # Handle UNC paths (\\server\share\...)
    # os.path.normpath converts \\ to \ but we need to handle the split correctly
    is_unc = path.startswith('\\\\') or dwg_path.startswith('\\\\')

    # Split by backslash (works for both UNC and regular paths on Windows)
    parts = path.replace('/', '\\').split('\\')

    # Remove empty parts (from leading \\ in UNC paths)
    parts = [p for p in parts if p]

    # Look for the "Projects" folder in the path
    try:
        projects_idx = None
        for i, part in enumerate(parts):
            if part.lower() == "projects":
                projects_idx = i
                break

        if projects_idx is not None and projects_idx + 4 < len(parts):
            # Project root is 4 levels down from "Projects": Nelson/BAC/2025/ProjectFolder
            root_parts = parts[:projects_idx + 5]

            # Reconstruct the path
            if is_unc:
                project_root = '\\\\' + '\\'.join(root_parts)
            else:
                project_root = '\\'.join(root_parts)

            return project_root
    except (ValueError, IndexError):
        pass

    # Fallback: walk up from the DWG location to find a folder
    # that contains typical project subfolders.
    try:
        current = os.path.abspath(dwg_path)
        if os.path.isfile(current):
            current = os.path.dirname(current)
    except OSError:
        return None

    while True:
        electrical = os.path.join(current, "Electrical")
        pdf = os.path.join(current, "PDF")
        if os.path.isdir(electrical) or os.path.isdir(pdf):
            return current

        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent

    return None


def find_pdf_folders(project_root):
    """
    Find PDF-related subfolders to scan for existing sheets.
    """
    if not project_root:
        return []

    folders = [
        os.path.join(project_root, "PDF"),
        os.path.join(project_root, "Electrical", "Checkset"),
    ]

    return [folder for folder in folders if os.path.isdir(folder)]


def get_recent_pdfs(folders, max_files=MAX_CANDIDATE_PDFS, max_seconds=MAX_SCAN_SECONDS):
    """
    Get a list of the most recent PDFs across multiple folders.
    Stops scanning when time budget is exceeded.
    """
    if not folders:
        return [], None

    deadline = time.monotonic() + max_seconds
    heap = []
    max_mtime = None

    for folder in folders:
        if time.monotonic() > deadline:
            break

        # Walk through all subdirectories to find PDFs
        for root, dirs, files in os.walk(folder):
            if time.monotonic() > deadline:
                break

            for file in files:
                if not file.lower().endswith('.pdf'):
                    continue

                full_path = os.path.join(root, file)
                try:
                    mtime = os.path.getmtime(full_path)
                    size = os.path.getsize(full_path)
                except OSError:
                    continue

                if size > MAX_PDF_BYTES:
                    continue

                if max_mtime is None or mtime > max_mtime:
                    max_mtime = mtime

                if len(heap) < max_files:
                    heapq.heappush(heap, (mtime, full_path))
                else:
                    if mtime > heap[0][0]:
                        heapq.heapreplace(heap, (mtime, full_path))

    if not heap:
        return [], max_mtime

    # Sort by modification time (most recent first)
    heap.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in heap], max_mtime


def _cache_path(project_root):
    return os.path.join(project_root, ".pdf_size_cache.json")


def load_cache(project_root):
    try:
        with open(_cache_path(project_root), "r", encoding="ascii") as cache_file:
            data = json.load(cache_file)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, UnicodeError):
        pass
    return {}


def save_cache(project_root, cache):
    try:
        with open(_cache_path(project_root), "w", encoding="ascii") as cache_file:
            json.dump(cache, cache_file)
    except OSError:
        pass


def _get_cached_dimensions(pdf_path, cache):
    pdf_cache = cache.get("pdf_page_cache", {})
    entry = pdf_cache.get(pdf_path)
    if not isinstance(entry, dict):
        return None

    try:
        mtime = os.path.getmtime(pdf_path)
        size = os.path.getsize(pdf_path)
    except OSError:
        return None

    if entry.get("mtime") != mtime or entry.get("size") != size:
        return None

    dims = entry.get("dimensions")
    if (isinstance(dims, list) and len(dims) == 2 and
            all(isinstance(value, (int, float)) for value in dims)):
        return (dims[0], dims[1])

    return None


def _update_pdf_cache(pdf_path, dimensions, cache):
    if not dimensions:
        return

    try:
        mtime = os.path.getmtime(pdf_path)
        size = os.path.getsize(pdf_path)
    except OSError:
        return

    pdf_cache = cache.setdefault("pdf_page_cache", {})
    pdf_cache[pdf_path] = {
        "mtime": mtime,
        "size": size,
        "dimensions": [dimensions[0], dimensions[1]],
    }


def detect_pdf_page_size(pdf_path):
    """
    Read a PDF file and return the page dimensions of the first page.
    Returns (width, height) in points.
    """
    try:
        with fitz.open(pdf_path) as pdf:
            if len(pdf) == 0:
                return None

            page = pdf.load_page(0)
            rect = page.rect
            width = rect.width
            height = rect.height

            # Ensure width is the smaller dimension (portrait normalization)
            # Actually, for engineering drawings, we want landscape (width > height)
            # So we normalize to ensure we're comparing correctly
            if width < height:
                width, height = height, width

            return (width, height)
    except Exception as e:
        print(f"Error reading PDF: {e}", file=sys.stderr)
        return None


def match_paper_size(dimensions):
    """
    Match detected dimensions to a standard paper size.
    Returns the paper size name or None if no match.
    """
    if not dimensions:
        return None

    detected_width, detected_height = dimensions

    for size_name, (std_width, std_height) in PAPER_SIZES.items():
        # Check both orientations
        if (abs(detected_width - std_width) <= TOLERANCE and
            abs(detected_height - std_height) <= TOLERANCE):
            return size_name
        if (abs(detected_width - std_height) <= TOLERANCE and
            abs(detected_height - std_width) <= TOLERANCE):
            return size_name

    return None


def detect_paper_size(dwg_path):
    """
    Main function to detect paper size from existing PDFs in the project.
    Returns the matching paper size name or empty string if not found.
    """
    project_root = get_project_root(dwg_path)
    if not project_root:
        return ""

    pdf_folders = find_pdf_folders(project_root)
    if not pdf_folders:
        return ""

    recent_pdfs, max_mtime = get_recent_pdfs(pdf_folders)
    if not recent_pdfs:
        return ""

    cache = load_cache(project_root)
    cache_dirty = False
    if max_mtime is not None:
        cached_size = cache.get("paper_size")
        cached_mtime = cache.get("max_mtime")
        if (cached_size in PAPER_SIZES and isinstance(cached_mtime, (int, float)) and
                cached_mtime >= max_mtime):
            return cached_size

    for pdf_path in recent_pdfs:
        dimensions = _get_cached_dimensions(pdf_path, cache)
        if not dimensions:
            dimensions = detect_pdf_page_size(pdf_path)
            if dimensions:
                _update_pdf_cache(pdf_path, dimensions, cache)
                cache_dirty = True
        if not dimensions:
            continue

        matched_size = match_paper_size(dimensions)
        if matched_size:
            cache["paper_size"] = matched_size
            cache["max_mtime"] = max_mtime
            save_cache(project_root, cache)
            return matched_size

    if cache_dirty:
        save_cache(project_root, cache)

    return ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detect_pdf_size.py <dwg_path>", file=sys.stderr)
        sys.exit(1)

    dwg_path = sys.argv[1]
    result = detect_paper_size(dwg_path)

    # Output the result (will be captured by PowerShell)
    print(result)
