"""Ultra-fast multi-label keyboard photo labeler & 1-click trainer for ACIES Panel Schedule AI.

Supports mixed photos! Toggle ANY combination of the 6 tags visible in a photo:
    1          -> Toggle Panel Name Tag (engraved placard / sticker / Sharpie panel ID)
    2          -> Toggle Factory Nameplate (spec plate: Model #, Amps, Voltage, Phase)
    3          -> Toggle Wiring / SCCR / UL Label (inside-door wiring diagram, SCCR, torque, UL)
    4          -> Toggle Circuit Breakers
    5          -> Toggle Circuit Directory
    6          -> Toggle Main Breaker / MLO
    A          -> Toggle Full Panelboard (panel_tag + breakers + directory + main_breaker)
    Enter      -> Save selected tag(s) & advance
    Space / 0  -> Instant "Not Panel" & advance (1 keypress for rooms/ceilings/HVAC/etc.)
    S          -> Skip photo
    Z / Bksp   -> Undo last label
    R          -> Rotate preview 90 degrees

Click any count chip at the top (e.g. "2. Nameplate") to queue already-labeled photos
of that tag for quick review / re-tagging in place.

Saves non-destructive copies into:
    %USERPROFILE%\\Documents\\ProjectManagementApp\\panel_dataset\\images\\
and records multi-label tags in:
    %USERPROFILE%\\Documents\\ProjectManagementApp\\panel_dataset\\labels.json
(also reads any photos already placed into legacy subfolders).

Launch:
    Double-click label_panel_photos.cmd
    or: .venv\\Scripts\\python.exe scripts/panel_photo_labeler.py
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import socket
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import panel_photo_prefilter as pf
import panel_schedule_ai as psa
from scripts import train_panel_classifier as trainer

VALID_TAGS = list(trainer.TAG_NAMES)
APP_DATA_DIR = Path.home() / "Documents" / "ProjectManagementApp"


def _resolve_gemini_api_key() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass
    settings_path = APP_DATA_DIR / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            key = str(data.get("apiKey") or "").strip()
            if key:
                return key
        except Exception:
            pass
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def _file_fingerprint(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        chunk = f.read(65536)
        h.update(chunk)
    st = path.stat()
    h.update(f"|{st.st_size}".encode("ascii"))
    return h.hexdigest()[:16]


class LabelerSession:
    def __init__(self, dataset_dir: Path) -> None:
        self.dataset_dir = dataset_dir
        trainer.ensure_dataset_folders(self.dataset_dir)
        self.labels_path = self.dataset_dir / "labels.json"
        self.lock = threading.RLock()
        self.labels: Dict[str, Dict[str, Any]] = self._load_labels()
        self.queue: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []
        self.loaded_folders: List[str] = []
        self.last_train_result: Optional[Dict[str, Any]] = None

    def _load_labels(self) -> Dict[str, Dict[str, Any]]:
        loaded: Dict[str, Dict[str, Any]] = {}
        if self.labels_path.exists():
            try:
                raw = json.loads(self.labels_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    loaded.update(raw)
            except Exception:
                pass
        # Migrate any existing files in legacy subfolders so previous labels are preserved!
        for folder_name, folder_tags in trainer.LEGACY_FOLDER_TO_TAGS.items():
            cls_dir = self.dataset_dir / folder_name
            if not cls_dir.exists():
                continue
            for fp in pf.scan_folder_for_images(cls_dir, recursive=True):
                try:
                    fp_hash = _file_fingerprint(fp)
                    if fp_hash not in loaded:
                        rel = str(fp.relative_to(self.dataset_dir)).replace("\\", "/")
                        loaded[fp_hash] = {"file": rel, "tags": list(folder_tags)}
                except Exception:
                    continue
        return loaded

    def _save_labels(self) -> None:
        try:
            tmp = self.labels_path.with_name("labels.tmp.json")
            tmp.write_text(json.dumps(self.labels, indent=2), encoding="utf-8")
            os.replace(tmp, self.labels_path)
        except Exception:
            pass

    def get_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {
            "total": 0,
            "panel_any": 0,
            "not_panel": 0,
            "multi_tag": 0,
            **{t: 0 for t in VALID_TAGS},
        }
        for entry in self.labels.values():
            tags = [t for t in (entry.get("tags") or []) if t in VALID_TAGS]
            counts["total"] += 1
            if tags:
                counts["panel_any"] += 1
                if len(tags) > 1:
                    counts["multi_tag"] += 1
                for t in tags:
                    counts[t] += 1
            else:
                counts["not_panel"] += 1
        return counts

    def add_folder(self, folder_path: str) -> Dict[str, Any]:
        root = Path(str(folder_path or "").strip().strip('"'))
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Folder not found: {root}")
        found = pf.scan_folder_for_images(root, recursive=True)
        added = 0
        skipped_existing = 0
        with self.lock:
            existing_queue_hashes = {item["hash"] for item in self.queue}
            for fp in found:
                try:
                    fp_hash = _file_fingerprint(fp)
                except Exception:
                    continue
                if fp_hash in self.labels or fp_hash in existing_queue_hashes:
                    skipped_existing += 1
                    continue
                existing_queue_hashes.add(fp_hash)
                self.queue.append(
                    {
                        "id": fp_hash,
                        "path": str(fp),
                        "name": fp.name,
                        "relFolder": str(fp.parent.name),
                        "hash": fp_hash,
                        "suggestedTags": [],
                        "suggestionConf": 0.0,
                    }
                )
                added += 1
            folder_str = str(root)
            if folder_str not in self.loaded_folders:
                self.loaded_folders.append(folder_str)
        return {
            "folder": str(root),
            "found": len(found),
            "added": added,
            "skippedAlreadyLabeled": skipped_existing,
            "queueRemaining": len(self.queue),
        }

    def queue_existing_by_tag(self, tag: str) -> Dict[str, Any]:
        """Prepend already-labeled dataset photos matching a tag to the queue for fast re-labeling."""
        clean = str(tag or "").strip().lower()
        queued = 0
        with self.lock:
            existing_ids = {it["id"] for it in self.queue}
            items_to_prepend: List[Dict[str, Any]] = []
            for fp_hash, entry in self.labels.items():
                if fp_hash in existing_ids:
                    continue
                tags = [t for t in (entry.get("tags") or []) if t in VALID_TAGS]
                if clean == "not_panel":
                    match = len(tags) == 0
                elif clean == "multi_tag":
                    match = len(tags) > 1
                elif clean in VALID_TAGS:
                    match = clean in tags
                else:
                    match = False
                if not match:
                    continue
                rel = str(entry.get("file") or "").strip()
                if not rel:
                    continue
                fp = Path(rel)
                if not fp.is_absolute():
                    fp = self.dataset_dir / fp
                if not fp.exists():
                    continue
                items_to_prepend.append(
                    {
                        "id": fp_hash,
                        "path": str(fp),
                        "name": fp.name,
                        "relFolder": f"relabel:{clean}",
                        "hash": fp_hash,
                        "existing": True,
                        "currentTags": list(tags),
                        "suggestedTags": list(tags),
                        "suggestionConf": 0.0,
                    }
                )
                existing_ids.add(fp_hash)
                queued += 1
            if items_to_prepend:
                self.queue = items_to_prepend + self.queue
        return {"tag": clean, "queued": queued, "state": self.get_state()}

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
            counts = self.get_counts()
            preview = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "relFolder": item["relFolder"],
                    "existing": bool(item.get("existing", False)),
                    "currentTags": list(item.get("currentTags") or []),
                    "suggestedTags": list(item.get("suggestedTags") or []),
                    "suggestionConf": item.get("suggestionConf", 0.0),
                }
                for item in self.queue[:5]
            ]
            pf_status = pf.get_prefilter_status(APP_DATA_DIR)
            return {
                "datasetDir": str(self.dataset_dir),
                "counts": counts,
                "totalLabeled": counts["total"],
                "queueRemaining": len(self.queue),
                "canUndo": len(self.history) > 0,
                "upcoming": preview,
                "loadedFolders": list(self.loaded_folders),
                "hasApiKey": bool(_resolve_gemini_api_key()),
                "prefilterStatus": pf_status,
                "lastTrainResult": self.last_train_result,
            }

    def find_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            for item in self.queue:
                if item["id"] == item_id:
                    return item
        return None

    def label_current(
        self,
        item_id: str,
        tags: Optional[Sequence[str]] = None,
        *,
        skip: bool = False,
    ) -> Dict[str, Any]:
        with self.lock:
            if not self.queue:
                raise ValueError("Queue is empty.")
            idx = next((i for i, it in enumerate(self.queue) if it["id"] == item_id), 0)
            item = self.queue.pop(idx)

            if skip:
                self.history.append({"action": "skip", "item": item})
                return self.get_state()

            clean_tags = sorted({str(t).strip().lower() for t in (tags or []) if str(t).strip().lower() in VALID_TAGS})
            prev_entry = dict(self.labels[item["hash"]]) if item["hash"] in self.labels else None

            if item.get("existing") and prev_entry is not None:
                updated_entry = dict(prev_entry)
                updated_entry["tags"] = clean_tags
                self.labels[item["hash"]] = updated_entry
                self._save_labels()
                self.history.append(
                    {
                        "action": "relabel",
                        "item": item,
                        "prevEntry": prev_entry,
                    }
                )
                return self.get_state()

            src = Path(item["path"])
            images_dir = self.dataset_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            safe_stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in src.stem)[:60]
            dest = images_dir / f"{item['hash']}_{safe_stem}{src.suffix.lower()}"
            if not dest.exists():
                shutil.copy2(src, dest)
            rel_file = f"images/{dest.name}"

            self.labels[item["hash"]] = {
                "file": rel_file,
                "tags": clean_tags,
                "source": str(src),
            }
            self._save_labels()
            self.history.append({"action": "label", "item": item, "tags": clean_tags, "dest": str(dest)})
            return self.get_state()

    def undo_last(self) -> Dict[str, Any]:
        with self.lock:
            if not self.history:
                return self.get_state()
            last = self.history.pop()
            item = last["item"]
            if last["action"] == "relabel":
                if last.get("prevEntry") is not None:
                    self.labels[item["hash"]] = last["prevEntry"]
                    self._save_labels()
            elif last["action"] == "label":
                dest = Path(last["dest"])
                if dest.exists():
                    try:
                        dest.unlink()
                    except Exception:
                        pass
                self.labels.pop(item["hash"], None)
                self._save_labels()
            self.queue.insert(0, item)
            return self.get_state()

    def prelabel_next_batch(self, count: int = 18) -> Dict[str, Any]:
        api_key = _resolve_gemini_api_key()
        if not api_key:
            raise RuntimeError("No Gemini API key found in Settings or .env.")
        with self.lock:
            batch = list(self.queue[: max(1, min(count, 18))])
        if not batch:
            return {"suggested": 0, "state": self.get_state()}

        sources = [
            {"id": it["id"], "kind": "image", "name": it["name"], "path": it["path"], "pageLabel": it["name"]}
            for it in batch
        ]
        res = psa.sort_survey_photos_with_decision_api(sources=sources, api_key=api_key, split_panels=False)
        assign_map = {a["id"]: a for a in res.get("assignments") or []}
        updated = 0
        with self.lock:
            for item in self.queue:
                a = assign_map.get(item["id"])
                if not a:
                    continue
                bkt = a.get("bucket") or "ignore"
                if bkt == "ignore":
                    item["suggestedTags"] = []
                elif bkt == "full_panel":
                    item["suggestedTags"] = ["panel_tag", "breakers", "directory", "main_breaker"]
                elif bkt in VALID_TAGS:
                    item["suggestedTags"] = [bkt]
                else:
                    item["suggestedTags"] = []
                item["suggestionConf"] = float(a.get("confidence") or 0.0)
                updated += 1
        return {"suggested": updated, "state": self.get_state()}

    def train_now(self) -> Dict[str, Any]:
        result = trainer.train_from_dataset(self.dataset_dir, app_data_dir=APP_DATA_DIR)
        with self.lock:
            self.last_train_result = result
        return result


def _pick_folder_native() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Select Site Survey Photos Folder")
        root.destroy()
        return str(folder or "")
    except Exception:
        return ""


HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ACIES Multi-Label Panel Photo Labeler &amp; Trainer</title>
<style>
  :root {
    --bg: #0b1110;
    --panel: #121b19;
    --panel2: #182522;
    --border: rgba(255,255,255,0.10);
    --text: #eef5f2;
    --muted: #8ea39b;
    --accent: #10b981;
    --warn: #f59e0b;
    --danger: #ef4444;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text); font-family: Inter, Segoe UI, system-ui, sans-serif; overflow: hidden; }
  .app { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; height: 100%; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--border); flex-wrap: wrap; }
  .brand { font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 10px; }
  .pill { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 999px; background: rgba(16,185,129,0.16); color: var(--accent); border: 1px solid rgba(16,185,129,0.35); }
  .controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  input[type="text"] { width: 300px; padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 12px; }
  button { padding: 7px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--panel2); color: var(--text); font-size: 12px; font-weight: 600; cursor: pointer; }
  button:hover { border-color: var(--accent); }
  button.primary { background: var(--accent); color: #04130d; border-color: var(--accent); }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  .counts-bar { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 16px; background: var(--panel2); border-bottom: 1px solid var(--border); font-size: 12px; flex-wrap: wrap; }
  .count-pills { display: flex; gap: 6px; flex-wrap: wrap; }
  .count-chip { padding: 4px 9px; border-radius: 7px; background: var(--panel); border: 1px solid var(--border); color: var(--text); font-size: 11.5px; font-weight: 500; cursor: pointer; transition: border-color 0.12s ease, background 0.12s ease; }
  .count-chip:hover { border-color: var(--accent); background: rgba(16,185,129,0.12); }
  .count-chip strong { color: var(--accent); margin-left: 4px; }
  .stage { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; overflow: hidden; padding: 14px; }
  .photo-meta { position: absolute; top: 10px; left: 16px; right: 16px; display: flex; justify-content: space-between; align-items: center; gap: 10px; font-size: 12px; color: var(--muted); pointer-events: none; }
  .suggestion-banner { padding: 4px 11px; border-radius: 999px; background: rgba(245,158,11,0.16); border: 1px solid rgba(245,158,11,0.45); color: #fbbf24; font-weight: 700; font-size: 12px; }
  .suggestion-banner.is-relabel { background: rgba(56,189,248,0.16); border-color: rgba(56,189,248,0.45); color: #38bdf8; }
  #photoImg { max-width: 92vw; max-height: 58vh; object-fit: contain; border-radius: 10px; box-shadow: 0 18px 50px rgba(0,0,0,0.65); transition: transform 0.1s ease; }
  .empty { text-align: center; max-width: 600px; color: var(--muted); line-height: 1.55; }
  .empty h2 { color: var(--text); margin: 0 0 8px; font-size: 18px; }
  footer { display: flex; flex-direction: column; gap: 8px; padding: 10px 16px; background: var(--panel); border-top: 1px solid var(--border); }
  .tag-row { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
  .action-row { display: grid; grid-template-columns: 1.3fr 1.6fr 1.3fr 0.8fr 0.8fr; gap: 8px; }
  .key-btn { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; padding: 8px 6px; font-size: 12px; border-radius: 9px; transition: background 0.12s ease, border-color 0.12s ease; }
  .key-btn small { font-size: 10px; font-weight: 400; color: var(--muted); }
  .key-btn kbd { font-size: 11px; padding: 1px 6px; border-radius: 5px; background: rgba(255,255,255,0.10); color: var(--accent); font-family: Consolas, monospace; }
  .key-btn.is-on { background: rgba(16,185,129,0.22); border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
  .key-btn.is-on kbd { background: var(--accent); color: #04130d; }
  .key-btn.is-on small { color: #bbf7d0; }
  .key-btn.not-panel kbd { color: #f87171; }
  .key-btn.save-btn { background: var(--accent); color: #04130d; border-color: var(--accent); }
  .key-btn.save-btn kbd { background: rgba(0,0,0,0.22); color: #fff; }
  .status-line { display: flex; justify-content: space-between; align-items: center; gap: 12px; font-size: 11.5px; color: var(--muted); flex-wrap: wrap; }
  .modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,0.75); display: flex; align-items: center; justify-content: center; padding: 20px; z-index: 30; }
  .modal-bg[hidden] { display: none !important; }
  .modal-card { width: min(680px, 100%); max-height: 85vh; overflow: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 20px; }
  .modal-card h3 { margin: 0 0 10px; }
  pre { background: var(--bg); padding: 12px; border-radius: 10px; font-size: 12px; overflow: auto; border: 1px solid var(--border); }
</style>
</head>
<body>
<div class="app">
  <header>
    <div class="brand">
      ACIES Multi-Label Photo Labeler
      <span id="modelPill" class="pill">Multi-label ready</span>
    </div>
    <div class="controls">
      <input id="folderInput" type="text" placeholder="Paste Survey/Photos folder path or click Browse..." />
      <button id="browseBtn" type="button">Browse Folder...</button>
      <button id="loadBtn" type="button">Load Folder</button>
      <button id="prelabelBtn" type="button" title="Use gemini-decision-1 to suggest tags on next 18 photos">AI Suggest Next 18</button>
      <button id="trainBtn" class="primary" type="button">Train ACIES Model Now</button>
    </div>
  </header>

  <div class="counts-bar">
    <div class="count-pills">
      <button class="count-chip" type="button" data-review-tag="panel_tag" title="Click to review &amp; re-label existing Panel Name Tag photos">1. Panel Tag <strong id="cnt-panel_tag">0</strong></button>
      <button class="count-chip" type="button" data-review-tag="nameplate" title="Click to review &amp; re-label existing Factory Nameplate photos">2. Nameplate <strong id="cnt-nameplate">0</strong></button>
      <button class="count-chip" type="button" data-review-tag="wiring_label" title="Click to review &amp; re-label existing Wiring / SCCR / UL Label photos">3. Wiring/SCCR <strong id="cnt-wiring_label">0</strong></button>
      <button class="count-chip" type="button" data-review-tag="breakers" title="Click to review &amp; re-label existing Circuit Breaker photos">4. Breakers <strong id="cnt-breakers">0</strong></button>
      <button class="count-chip" type="button" data-review-tag="directory" title="Click to review &amp; re-label existing Circuit Directory photos">5. Directory <strong id="cnt-directory">0</strong></button>
      <button class="count-chip" type="button" data-review-tag="main_breaker" title="Click to review &amp; re-label existing Main Breaker photos">6. Main <strong id="cnt-main_breaker">0</strong></button>
      <button class="count-chip" type="button" data-review-tag="multi_tag" title="Click to review existing multi-tag photos">Multi-Tag <strong id="cnt-multi_tag">0</strong></button>
      <button class="count-chip" type="button" data-review-tag="not_panel" title="Click to review existing Not Panel photos">Not Panel <strong id="cnt-not_panel">0</strong></button>
    </div>
    <div id="queueCount" style="color: var(--muted);">Queue: 0 remaining</div>
  </div>

  <main class="stage">
    <div class="photo-meta">
      <div id="photoName"></div>
      <div id="suggestionBanner" class="suggestion-banner" hidden></div>
    </div>
    <img id="photoImg" alt="Survey photo to label" hidden />
    <div id="emptyState" class="empty">
      <h2>Multi-Label Site Survey Photo Labeler</h2>
      <p>Toggle <strong>any combination</strong> of the 6 tags visible in each photo — e.g. <strong>1 + 4</strong> for Panel Tag &amp; Breakers, <strong>3</strong> for Wiring Diagram / SCCR / UL Label, or <strong>A</strong> for a Full Panelboard — then press <strong>Enter</strong> to save.<br/>Press <strong>Space</strong> to immediately mark <strong>Not Panel</strong> in 1 tap. Click any tag count chip above to review &amp; re-tag existing photos.</p>
    </div>
  </main>

  <footer>
    <div class="tag-row">
      <button class="key-btn" data-tag="panel_tag" type="button"><kbd>1</kbd><span>Panel Name Tag</span><small>Placard / ID sticker</small></button>
      <button class="key-btn" data-tag="nameplate" type="button"><kbd>2</kbd><span>Factory Nameplate</span><small>Model / Amps / Volts</small></button>
      <button class="key-btn" data-tag="wiring_label" type="button"><kbd>3</kbd><span>Wiring / SCCR / UL</span><small>Diagram / AIC / Torque</small></button>
      <button class="key-btn" data-tag="breakers" type="button"><kbd>4</kbd><span>Circuit Breakers</span><small>Branch handles</small></button>
      <button class="key-btn" data-tag="directory" type="button"><kbd>5</kbd><span>Circuit Directory</span><small>Door schedule card</small></button>
      <button class="key-btn" data-tag="main_breaker" type="button"><kbd>6</kbd><span>Main Breaker / MLO</span><small>Main disconnect</small></button>
    </div>
    <div class="action-row">
      <button class="key-btn" id="allTagsBtn" type="button" title="Toggle Panel Tag + Breakers + Directory + Main Breaker"><kbd>A</kbd><span>Full Panel (1+4+5+6)</span></button>
      <button class="key-btn save-btn" id="saveTagsBtn" type="button"><kbd>Enter</kbd><span id="saveBtnLabel">Save Tags</span></button>
      <button class="key-btn not-panel" id="notPanelBtn" type="button" title="Immediately mark Not Panel and advance"><kbd>Space</kbd><span>Not Panel (1-Tap)</span></button>
      <button class="key-btn" id="skipBtn" type="button"><kbd>S</kbd><span>Skip</span></button>
      <button class="key-btn" id="undoBtn" type="button"><kbd>Z</kbd><span>Undo</span></button>
    </div>
    <div class="status-line">
      <span id="statusText">Toggle 1–6 (or A for Full Panel) then press Enter. Press Space for instant Not Panel. Click any count chip above to re-label existing photos.</span>
      <span id="datasetPath"></span>
    </div>
  </footer>
</div>

<div id="trainModal" class="modal-bg" hidden>
  <div class="modal-card">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <h3>ACIES Multi-Label Panel Classifier Report</h3>
      <button id="closeTrainModal" type="button">Close</button>
    </div>
    <p style="font-size:12.5px;color:var(--muted);margin-top:4px;">Your trained multi-label weights are automatically active in <strong>Panel Schedule AI Studio</strong> immediately.</p>
    <pre id="trainReportPre"></pre>
  </div>
</div>

<script>
(() => {
  const FULL_PANEL_TAGS = ["panel_tag", "breakers", "directory", "main_breaker"];
  let state = null;
  let selectedTags = new Set();
  let lastPhotoId = "";
  let rotation = 0;
  let busy = false;
  const prefetched = new Set();

  const byId = (id) => document.getElementById(id);
  const setStatus = (msg) => { byId("statusText").textContent = msg; };

  async function apiCall(path, body = null) {
    const opts = body !== null
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : { method: "GET" };
    const r = await fetch(path, opts);
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || "Request failed");
    return data;
  }

  function renderTagButtons() {
    for (const btn of document.querySelectorAll(".key-btn[data-tag]")) {
      btn.classList.toggle("is-on", selectedTags.has(btn.dataset.tag));
    }
    const fullOn = FULL_PANEL_TAGS.every((t) => selectedTags.has(t));
    byId("allTagsBtn").classList.toggle("is-on", fullOn);
    const saveLbl = byId("saveBtnLabel");
    if (selectedTags.size === 0) {
      saveLbl.textContent = "Save (Not Panel)";
    } else if (fullOn && selectedTags.size === FULL_PANEL_TAGS.length) {
      saveLbl.textContent = "Save Full Panel";
    } else {
      saveLbl.textContent = `Save (${selectedTags.size} tag${selectedTags.size === 1 ? "" : "s"})`;
    }
  }

  function toggleTag(tag) {
    if (selectedTags.has(tag)) selectedTags.delete(tag);
    else selectedTags.add(tag);
    renderTagButtons();
  }

  function toggleFullPanelTags() {
    const fullOn = FULL_PANEL_TAGS.every((t) => selectedTags.has(t));
    if (fullOn) {
      for (const t of FULL_PANEL_TAGS) selectedTags.delete(t);
    } else {
      for (const t of FULL_PANEL_TAGS) selectedTags.add(t);
    }
    renderTagButtons();
  }

  function render() {
    if (!state) return;
    for (const [k, v] of Object.entries(state.counts || {})) {
      const el = byId("cnt-" + k);
      if (el) el.textContent = String(v);
    }
    byId("queueCount").textContent = `Queue: ${state.queueRemaining} remaining • Total labeled: ${state.totalLabeled}`;
    byId("datasetPath").textContent = state.datasetDir || "";
    byId("undoBtn").disabled = !state.canUndo || busy;
    byId("prelabelBtn").disabled = !state.hasApiKey || !state.queueRemaining || busy;
    byId("trainBtn").disabled = busy || (state.counts?.panel_any || 0) < 4 || (state.counts?.not_panel || 0) < 4;

    const pf = state.prefilterStatus || {};
    byId("modelPill").textContent = pf.customModelReady
      ? `Trained (${pf.customModelSamples} imgs • ${Math.round((pf.customModelMetrics?.panelF1 || 0) * 100)}% F1)`
      : "No custom model trained yet";

    const current = state.upcoming?.[0] || null;
    const img = byId("photoImg");
    const empty = byId("emptyState");
    const sugg = byId("suggestionBanner");

    if (!current) {
      lastPhotoId = "";
      selectedTags = new Set();
      renderTagButtons();
      img.hidden = true;
      empty.hidden = false;
      byId("photoName").textContent = "";
      sugg.hidden = true;
      return;
    }

    // Reset tag toggles cleanly whenever we advance to a new photo
    if (current.id !== lastPhotoId) {
      lastPhotoId = current.id;
      selectedTags = new Set(current.existing ? (current.currentTags || []) : (current.suggestedTags || []));
      rotation = 0;
      img.style.transform = "rotate(0deg)";
    }
    renderTagButtons();

    empty.hidden = true;
    img.hidden = false;
    img.src = `/api/image?id=${encodeURIComponent(current.id)}`;
    byId("photoName").textContent = `${current.relFolder} / ${current.name}`;

    sugg.classList.remove("is-relabel");
    if (current.existing) {
      const curTxt = (current.currentTags || []).length ? current.currentTags.join(" + ") : "not_panel";
      sugg.hidden = false;
      sugg.classList.add("is-relabel");
      sugg.textContent = `Re-labeling existing (currently: ${curTxt}) — toggle 1–6 then Enter to update`;
    } else if (current.suggestionConf > 0) {
      const tagTxt = (current.suggestedTags || []).length
        ? current.suggestedTags.join(" + ")
        : "not_panel";
      sugg.hidden = false;
      sugg.textContent = `AI pre-selected: ${tagTxt} (${Math.round(current.suggestionConf * 100)}%) — Enter to confirm or toggle 1–6`;
    } else {
      sugg.hidden = true;
    }

    for (const nextItem of (state.upcoming || []).slice(1, 4)) {
      if (!prefetched.has(nextItem.id)) {
        prefetched.add(nextItem.id);
        const pre = new Image();
        pre.src = `/api/image?id=${encodeURIComponent(nextItem.id)}`;
      }
    }
  }

  async function refresh() {
    state = await apiCall("/api/state");
    render();
  }

  async function submitTags(tagsArr, skip = false) {
    if (busy || !state?.upcoming?.length) return;
    const cur = state.upcoming[0];
    busy = true;
    try {
      state = await apiCall("/api/label", { id: cur.id, tags: tagsArr, skip });
      const desc = skip ? "Skipped" : (tagsArr.length ? tagsArr.join(" + ") : "not_panel");
      setStatus(`${cur.name} -> ${desc}`);
      lastPhotoId = "";
      render();
    } catch (e) {
      setStatus("Error: " + e.message);
    } finally {
      busy = false;
    }
  }

  async function doUndo() {
    if (busy || !state?.canUndo) return;
    busy = true;
    try {
      state = await apiCall("/api/undo", {});
      lastPhotoId = "";
      setStatus("Undid last action.");
      render();
    } catch (e) {
      setStatus("Error: " + e.message);
    } finally {
      busy = false;
    }
  }

  async function loadFolder(folderPath) {
    if (!folderPath) return;
    busy = true;
    setStatus("Scanning folder...");
    try {
      const res = await apiCall("/api/add_folder", { folder: folderPath });
      await refresh();
      setStatus(`Loaded ${res.added} new photo(s) from ${res.folder} (${res.skippedAlreadyLabeled} already labeled).`);
    } catch (e) {
      setStatus("Error: " + e.message);
    } finally {
      busy = false;
      render();
    }
  }

  async function queueExistingTag(tag) {
    if (busy) return;
    busy = true;
    try {
      const res = await apiCall("/api/queue_existing", { tag });
      state = res.state;
      lastPhotoId = "";
      setStatus(res.queued
        ? `Queued ${res.queued} existing '${tag}' photo(s) at the front for quick review / re-tagging.`
        : `No existing photos with tag '${tag}' to queue.`);
      render();
    } catch (e) {
      setStatus("Error: " + e.message);
    } finally {
      busy = false;
      render();
    }
  }

  byId("browseBtn").addEventListener("click", async () => {
    try {
      const res = await apiCall("/api/browse_folder", {});
      if (res.folder) {
        byId("folderInput").value = res.folder;
        await loadFolder(res.folder);
      }
    } catch (e) {
      setStatus("Error: " + e.message);
    }
  });

  byId("loadBtn").addEventListener("click", () => loadFolder(byId("folderInput").value.trim()));

  byId("prelabelBtn").addEventListener("click", async () => {
    busy = true;
    setStatus("Asking gemini-decision-1 to pre-suggest the next 18 photos...");
    render();
    try {
      const res = await apiCall("/api/prelabel", { count: 18 });
      state = res.state;
      lastPhotoId = "";
      setStatus(`Pre-labeled ${res.suggested} photo(s). Toggle 1–6 to adjust or press Enter to confirm.`);
    } catch (e) {
      setStatus("Error: " + e.message);
    } finally {
      busy = false;
      render();
    }
  });

  byId("trainBtn").addEventListener("click", async () => {
    busy = true;
    setStatus("Training custom multi-label ACIES model on your labeled dataset...");
    render();
    try {
      const res = await apiCall("/api/train", {});
      await refresh();
      const m = res.metadata.metrics || {};
      const lines = [
        `Saved to: ${res.outputPath}`,
        `Total Samples: ${res.metadata.sampleCount} (Panel: ${res.metadata.positiveCount}, Not Panel: ${res.metadata.negativeCount}, Multi-tag: ${res.metadata.classCounts?.multi_tag || 0})`,
        `Training Time: ${res.metadata.elapsedSec}s (${res.metadata.cvFolds}-fold cross-validation)`,
        ``,
        `Panel vs Not-Panel : Precision ${(m.panelPrecision * 100).toFixed(1)}% | Recall ${(m.panelRecall * 100).toFixed(1)}% | F1 ${(m.panelF1 * 100).toFixed(1)}%`,
        `Macro Tag F1       : ${(m.macroTagF1 * 100).toFixed(1)}%`,
        ``,
        `Per-Head Breakdown:`,
        ...Object.entries(m.perHead || {}).map(
          ([k, s]) => `  ${k.padEnd(14)} (n=${String(s.support).padStart(3)})  P=${(s.precision*100).toFixed(1).padStart(5)}%  R=${(s.recall*100).toFixed(1).padStart(5)}%  F1=${(s.f1*100).toFixed(1).padStart(5)}%`
        ),
      ];
      byId("trainReportPre").textContent = lines.join("\n");
      byId("trainModal").hidden = false;
      setStatus(`Model trained! Panel F1: ${(m.panelF1 * 100).toFixed(1)}% — active immediately in Panel Schedule AI Studio.`);
    } catch (e) {
      setStatus("Training error: " + e.message);
    } finally {
      busy = false;
      render();
    }
  });

  byId("closeTrainModal").addEventListener("click", () => { byId("trainModal").hidden = true; });
  byId("allTagsBtn").addEventListener("click", toggleFullPanelTags);
  byId("saveTagsBtn").addEventListener("click", () => submitTags(Array.from(selectedTags), false));
  byId("notPanelBtn").addEventListener("click", () => submitTags([], false));
  byId("skipBtn").addEventListener("click", () => submitTags([], true));
  byId("undoBtn").addEventListener("click", doUndo);
  for (const btn of document.querySelectorAll(".key-btn[data-tag]")) {
    btn.addEventListener("click", () => toggleTag(btn.dataset.tag));
  }
  for (const chip of document.querySelectorAll(".count-chip[data-review-tag]")) {
    chip.addEventListener("click", () => queueExistingTag(chip.dataset.reviewTag));
  }

  document.addEventListener("keydown", (e) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    if (!byId("trainModal").hidden) {
      if (e.key === "Escape") byId("trainModal").hidden = true;
      return;
    }
    if (e.key === "1") { e.preventDefault(); toggleTag("panel_tag"); }
    else if (e.key === "2") { e.preventDefault(); toggleTag("nameplate"); }
    else if (e.key === "3") { e.preventDefault(); toggleTag("wiring_label"); }
    else if (e.key === "4") { e.preventDefault(); toggleTag("breakers"); }
    else if (e.key === "5") { e.preventDefault(); toggleTag("directory"); }
    else if (e.key === "6") { e.preventDefault(); toggleTag("main_breaker"); }
    else if (e.key.toLowerCase() === "a") { e.preventDefault(); toggleFullPanelTags(); }
    else if (e.key === "Enter") { e.preventDefault(); submitTags(Array.from(selectedTags), false); }
    else if (e.key === " " || e.key === "0") { e.preventDefault(); submitTags([], false); }
    else if (e.key.toLowerCase() === "s") { e.preventDefault(); submitTags([], true); }
    else if (e.key.toLowerCase() === "z" || e.key === "Backspace") { e.preventDefault(); doUndo(); }
    else if (e.key.toLowerCase() === "r") {
      e.preventDefault();
      rotation = (rotation + 90) % 360;
      byId("photoImg").style.transform = `rotate(${rotation}deg)`;
    }
  });

  void refresh();
})();
</script>
</body>
</html>
"""


def make_handler(session: LabelerSession):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, data: Dict[str, Any], status: int = HTTPStatus.OK) -> None:
            raw = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                body = HTML_PAGE.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/state":
                self._send_json(session.get_state())
                return

            if parsed.path == "/api/image":
                qs = parse_qs(parsed.query)
                item_id = (qs.get("id") or [""])[0]
                item = session.find_item(item_id)
                if not item:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                try:
                    img = psa._open_normalized_pil(Path(item["path"]), max_edge=1400)
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
                    img.close()
                    raw = buf.getvalue()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "public, max-age=3600")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                body = self._read_json()
                if parsed.path == "/api/browse_folder":
                    self._send_json({"folder": _pick_folder_native()})
                elif parsed.path == "/api/add_folder":
                    self._send_json(session.add_folder(body.get("folder", "")))
                elif parsed.path == "/api/queue_existing":
                    self._send_json(session.queue_existing_by_tag(body.get("tag", "")))
                elif parsed.path == "/api/label":
                    self._send_json(
                        session.label_current(
                            body.get("id", ""),
                            body.get("tags") or [],
                            skip=bool(body.get("skip", False)),
                        )
                    )
                elif parsed.path == "/api/undo":
                    self._send_json(session.undo_last())
                elif parsed.path == "/api/prelabel":
                    self._send_json(session.prelabel_next_batch(int(body.get("count") or 18)))
                elif parsed.path == "/api/train":
                    self._send_json(session.train_now())
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    return Handler


def _find_free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return int(s.getsockname()[1])
            except OSError:
                continue
    return 8765


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast multi-label keyboard photo labeler & trainer.")
    parser.add_argument("--dataset", type=str, default=str(trainer.get_default_dataset_dir()))
    parser.add_argument("--folder", action="append", default=[], help="Initial survey photo folder(s) to queue.")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the web browser.")
    args = parser.parse_args()

    session = LabelerSession(Path(args.dataset))
    for folder in args.folder:
        try:
            res = session.add_folder(folder)
            print(f"Queued {res['added']} photo(s) from {res['folder']}")
        except Exception as exc:
            print(f"Warning: could not load {folder}: {exc}")

    port = _find_free_port(8765)
    url = f"http://127.0.0.1:{port}/"
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(session))
    print(f"\nACIES Multi-Label Panel Photo Labeler running at: {url}")
    print(f"Dataset directory: {session.dataset_dir}")
    print("Press Ctrl+C in this terminal to stop.\n")

    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
