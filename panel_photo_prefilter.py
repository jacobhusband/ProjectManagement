"""Local zero-shot ONNX visual pre-filter for site survey photos ($0 API tokens).

Narrows down large site survey folders (100–300+ photos of rooms, ceilings,
exteriors, HVAC, and conduits) to just the electrical panelboard candidates
(panel tags/nameplates, circuit breakers, circuit directories, main breakers)
BEFORE calling ``gemini-decision-1`` or ``gemini-4-hydrogen``.

Runs 100% locally on Windows CPU using ``onnxruntime`` + ``Xenova/clip-vit-base-patch32``
(int8 quantized, ~145 MB cached once in the app data directory). Also performs:
- EXIF capture-timestamp chronological sorting
- OpenCV Laplacian sharpness scoring (keeps the sharpest shot in duplicate bursts)
- Perceptual 64-bit dHash near-duplicate pruning
- Timeline gap metadata (elapsed seconds + count of dropped non-panel photos
  between consecutive panel candidates) to dramatically improve downstream
  multi-panel boundary detection in ``gemini-decision-1``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

PREFILTER_MODEL_ID = "Xenova/clip-vit-base-patch32"
PREFILTER_HF_BASE = f"https://huggingface.co/{PREFILTER_MODEL_ID}/resolve/main"
PREFILTER_FILES = {
    "vision": ("onnx/vision_model_int8.onnx", "vision_model_int8.onnx"),
    "text": ("onnx/text_model_int8.onnx", "text_model_int8.onnx"),
    "tokenizer": ("tokenizer.json", "tokenizer.json"),
}
PREFILTER_CACHE_SUBDIR = "clip-vit-base-patch32"
PREFILTER_EMBEDDINGS_VERSION = "v2"

# CLIP ViT-B/32 preprocessing constants (matching Xenova/clip-vit-base-patch32/preprocessor_config.json)
CLIP_IMAGE_SIZE = 224
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32).reshape(3, 1, 1)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32).reshape(3, 1, 1)
CLIP_LOGIT_SCALE = 100.0
CLIP_MAX_TOKENS = 77

# Sensitivity presets (calibrated for 2-way max-pos vs max-neg CLIP margin)
SENSITIVITY_THRESHOLDS = {
    "high_recall": 0.28,
    "balanced": 0.42,
    "strict": 0.58,
}
DEFAULT_SENSITIVITY = "balanced"
DUPLICATE_DHASH_MAX_DISTANCE = 9
MIN_SHARPNESS_WARN = 18.0

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".heic",
    ".heif",
}

# Multi-prompt ensembles for robust zero-shot electrical panel screening.
POSITIVE_PROMPT_GROUPS: Dict[str, Tuple[str, ...]] = {
    "panel_tag": (
        "a small engraved plastic phenolic name tag or sticker identifying an electrical panel such as PANEL L1 or PANEL H1",
        "a printed Brady label or handwritten panel name tag stuck on a gray metal electrical cabinet door",
    ),
    "nameplate": (
        "a metal electrical panelboard factory nameplate rating label showing catalog number voltage amps and bus rating",
        "an electrical panelboard manufacturer specification sticker showing 120 208V or 277 480V three phase four wire",
    ),
    "wiring_label": (
        "a printed electrical panelboard typical wiring diagram and short circuit current rating sticker glued inside a gray metal door",
        "an inside panelboard door technical chart showing terminal wire ranges tightening torque SCCR table and UL class CTL panelboard label",
    ),
    "breakers": (
        "a close-up photo of electrical circuit breakers inside an open breaker box panel",
        "rows of black circuit breaker switches inside a metal electrical panelboard",
        "an electrical distribution panel deadfront showing breaker handles and amp ratings",
    ),
    "directory": (
        "a printed or handwritten electrical panel circuit directory chart taped inside a metal door",
        "a paper circuit schedule table listing circuit numbers and room labels inside an electrical panel",
        "a typed electrical panel schedule sheet with columns of circuit descriptions and loads",
    ),
    "main_breaker": (
        "a close-up photo of a large main circuit breaker switch or main electrical lugs inside a panel",
        "a heavy-duty molded case main breaker handle inside an electrical distribution panelboard",
    ),
    "full_panel": (
        "a wide full view photo of an open electrical panelboard showing circuit breakers and the circuit directory on the open door",
        "an entire open metal electrical breaker box on a wall with breakers label and door schedule visible together",
    ),
}

# Map fine-grained classifier tags to Panel Schedule AI Studio's 5 drop-zone buckets.
TAG_TO_STUDIO_BUCKET: Dict[str, str] = {
    "panel_tag": "nameplate",
    "nameplate": "nameplate",
    "wiring_label": "nameplate",
    "breakers": "breakers",
    "directory": "directory",
    "main_breaker": "main_breaker",
    "full_panel": "full_panel",
}

NEGATIVE_PROMPT_GROUPS: Dict[str, Tuple[str, ...]] = {
    "Room / Interior": (
        "an indoor office room hallway conference room lobby or commercial interior space",
    ),
    "Ceiling / Lighting": (
        "a commercial drop ceiling with fluorescent or LED light fixtures and ceiling tiles",
    ),
    "Exterior / Site": (
        "the exterior of a commercial building parking lot street sidewalk or outdoor sign",
    ),
    "Wall Outlet / Switch": (
        "a wall electrical outlet duplex receptacle light switch or thermostat mounted on drywall",
    ),
    "HVAC / Plumbing": (
        "rooftop HVAC unit air conditioner ductwork pipes water heater or mechanical equipment",
    ),
    "Conduit / Wiring": (
        "electrical conduit pipes ceiling junction boxes cables or rough-in wall framing",
    ),
    "Closed Door / Wall": (
        "a closed gray metal cabinet door on a plain wall or storage room shelves",
    ),
    "Blurry / Unusable": (
        "a very blurry dark out of focus photo of a floor or random object",
        "a plain blank solid gray wall surface or empty uniform background",
    ),
}

_SESSION_LOCK = threading.Lock()
_CACHED_SESSIONS: Dict[str, Dict[str, Any]] = {}
CUSTOM_CLASSIFIER_FILENAME = "acies_panel_classifier.npz"
_CUSTOM_CLASSIFIER_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def get_custom_classifier_path(model_dir: Path) -> Path:
    return Path(model_dir) / CUSTOM_CLASSIFIER_FILENAME


def invalidate_custom_classifier_cache() -> None:
    with _SESSION_LOCK:
        _CUSTOM_CLASSIFIER_CACHE.clear()


def load_custom_classifier(model_dir: Path) -> Optional[Dict[str, Any]]:
    """Load custom trained ACIES linear head if present, hot-reloading when updated on disk."""
    path = get_custom_classifier_path(model_dir)
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
    except Exception:
        return None
    key = str(path.resolve())
    with _SESSION_LOCK:
        cached = _CUSTOM_CLASSIFIER_CACHE.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        try:
            data = np.load(path, allow_pickle=False)
            weights = np.asarray(data["weights"], dtype=np.float32)
            bias = np.asarray(data["bias"], dtype=np.float32)
            classes = [str(c) for c in data["classes"].tolist()]
            mode = str(data["mode"].item()) if "mode" in data else "softmax"
            meta_raw = str(data["metadata_json"].item()) if "metadata_json" in data else "{}"
            metadata = json.loads(meta_raw) if meta_raw else {}
            if weights.ndim != 2 or bias.ndim != 1 or weights.shape[0] != len(classes):
                return None
            if mode == "multilabel_sigmoid":
                if "is_panel" not in classes:
                    return None
                record = {
                    "path": str(path),
                    "mode": "multilabel_sigmoid",
                    "weights": weights,
                    "bias": bias,
                    "classes": classes,
                    "isPanelIdx": classes.index("is_panel"),
                    "metadata": metadata,
                }
            else:
                if "not_panel" not in classes:
                    return None
                record = {
                    "path": str(path),
                    "mode": "softmax",
                    "weights": weights,
                    "bias": bias,
                    "classes": classes,
                    "notPanelIdx": classes.index("not_panel"),
                    "metadata": metadata,
                }
            _CUSTOM_CLASSIFIER_CACHE[key] = (mtime, record)
            return record
        except Exception as exc:
            logger.warning("Could not load custom panel classifier %s: %s", path, exc)
            return None


def _prompt_bank_signature() -> str:
    payload = json.dumps(
        {
            "version": PREFILTER_EMBEDDINGS_VERSION,
            "positive": POSITIVE_PROMPT_GROUPS,
            "negative": NEGATIVE_PROMPT_GROUPS,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def get_model_cache_dir(app_data_dir: Optional[str | Path] = None) -> Path:
    if app_data_dir:
        root = Path(app_data_dir) / "models" / PREFILTER_CACHE_SUBDIR
    else:
        root = Path.home() / "Documents" / "ProjectManagementApp" / "models" / PREFILTER_CACHE_SUBDIR
    return root


def is_runtime_available() -> Tuple[bool, str]:
    missing = []
    for mod in ("onnxruntime", "tokenizers"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    if missing:
        return False, f"Missing local filter dependencies: {', '.join(missing)}"
    return True, "ok"


def get_prefilter_status(app_data_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    runtime_ok, runtime_msg = is_runtime_available()
    model_dir = get_model_cache_dir(app_data_dir)
    files_present = all((model_dir / local_name).exists() for _, local_name in PREFILTER_FILES.values())
    size_mb = 0.0
    if files_present:
        total_bytes = sum((model_dir / local_name).stat().st_size for _, local_name in PREFILTER_FILES.values())
        size_mb = round(total_bytes / (1024 * 1024), 1)
    custom = load_custom_classifier(model_dir)
    custom_meta = custom["metadata"] if custom else {}
    return {
        "modelId": PREFILTER_MODEL_ID,
        "runtimeAvailable": runtime_ok,
        "runtimeMessage": runtime_msg,
        "modelReady": bool(runtime_ok and files_present),
        "customModelReady": bool(custom is not None),
        "customModelSamples": int(custom_meta.get("sampleCount") or 0),
        "customModelMetrics": custom_meta.get("metrics") or {},
        "customModelTrainedAt": str(custom_meta.get("trainedAt") or ""),
        "modelDir": str(model_dir),
        "cachedSizeMb": size_mb,
        "downloadSizeMb": 148,
    }


def _download_file(
    url: str,
    dest: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(f"{dest.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        with requests.get(url, stream=True, timeout=(10, 120)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(tmp_path, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)
        os.replace(tmp_path, dest)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def ensure_prefilter_model(
    app_data_dir: Optional[str | Path] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Path:
    """Ensure quantized CLIP ONNX vision/text models & tokenizer are cached locally."""
    runtime_ok, runtime_msg = is_runtime_available()
    if not runtime_ok:
        raise RuntimeError(f"{runtime_msg}. Install with: pip install onnxruntime tokenizers")

    model_dir = get_model_cache_dir(app_data_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    missing_entries = [
        (key, remote_rel, local_name)
        for key, (remote_rel, local_name) in PREFILTER_FILES.items()
        if not (model_dir / local_name).exists()
    ]
    if not missing_entries:
        return model_dir

    total_files = len(missing_entries)
    for idx, (key, remote_rel, local_name) in enumerate(missing_entries, start=1):
        url = f"{PREFILTER_HF_BASE}/{remote_rel}"
        dest = model_dir / local_name
        last_emit = [0.0]

        def _on_chunk(done_bytes: int, total_bytes: int) -> None:
            now = time.monotonic()
            if now - last_emit[0] < 0.25 and done_bytes < total_bytes:
                return
            last_emit[0] = now
            if progress_callback:
                done_mb = done_bytes / (1024 * 1024)
                total_mb = total_bytes / (1024 * 1024) if total_bytes > 0 else 0.0
                file_frac = (done_bytes / total_bytes) if total_bytes > 0 else 0.0
                pct = int(round(((idx - 1 + file_frac) / total_files) * 100))
                size_str = f"{done_mb:.1f} / {total_mb:.1f} MB" if total_mb > 0 else f"{done_mb:.1f} MB"
                progress_callback(
                    {
                        "stage": "download",
                        "progress": max(2, min(98, pct)),
                        "message": f"One-time model download ({idx}/{total_files}: {local_name}, {size_str})...",
                    }
                )

        if progress_callback:
            progress_callback(
                {
                    "stage": "download",
                    "progress": int(((idx - 1) / total_files) * 100),
                    "message": f"Downloading local vision model ({idx}/{total_files}: {local_name})...",
                }
            )
        logger.info("Downloading local panel pre-filter asset: %s -> %s", url, dest)
        _download_file(url, dest, progress_cb=_on_chunk)

    return model_dir


def _build_prompt_catalog() -> Tuple[List[str], List[Dict[str, Any]]]:
    prompts: List[str] = []
    meta: List[Dict[str, Any]] = []
    for bucket, texts in POSITIVE_PROMPT_GROUPS.items():
        for text in texts:
            prompts.append(text)
            meta.append({"isPositive": True, "label": bucket, "text": text})
    for neg_label, texts in NEGATIVE_PROMPT_GROUPS.items():
        for text in texts:
            prompts.append(text)
            meta.append({"isPositive": False, "label": neg_label, "text": text})
    return prompts, meta


def _l2_normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=-1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return arr / norms


def _pick_embedding_output(session, outputs: Sequence[np.ndarray]) -> np.ndarray:
    """Select the projected embedding tensor (e.g. image_embeds / text_embeds / pooler_output)."""
    names = [o.name for o in session.get_outputs()]
    for preferred in ("image_embeds", "text_embeds", "pooler_output", "sentence_embedding"):
        if preferred in names:
            return np.asarray(outputs[names.index(preferred)], dtype=np.float32)
    # Fallback: pick first 2D output tensor (batch, dim)
    for out in outputs:
        arr = np.asarray(out, dtype=np.float32)
        if arr.ndim == 2:
            return arr
    return np.asarray(outputs[0], dtype=np.float32)


def _compute_text_embeddings(model_dir: Path, prompts: Sequence[str]) -> np.ndarray:
    import onnxruntime as ort
    from tokenizers import Tokenizer

    cache_file = model_dir / f"prompt_embeds_{_prompt_bank_signature()}.npz"
    if cache_file.exists():
        try:
            loaded = np.load(cache_file)
            embeds = np.asarray(loaded["embeddings"], dtype=np.float32)
            if embeds.shape[0] == len(prompts):
                return embeds
        except Exception:
            pass

    tokenizer = Tokenizer.from_file(str(model_dir / PREFILTER_FILES["tokenizer"][1]))
    # Ensure CLIP BOS/EOS and fixed length padding/truncation to 77 tokens
    pad_id = tokenizer.token_to_id("<|endoftext|>")
    if pad_id is None:
        pad_id = 0
    tokenizer.enable_truncation(max_length=CLIP_MAX_TOKENS)
    tokenizer.enable_padding(length=CLIP_MAX_TOKENS, pad_id=pad_id)

    encodings = tokenizer.encode_batch(list(prompts))
    input_ids = np.array([enc.ids for enc in encodings], dtype=np.int64)
    attention_mask = np.array([enc.attention_mask for enc in encodings], dtype=np.int64)

    sess_opts = ort.SessionOptions()
    sess_opts.intra_op_num_threads = max(1, min(4, os.cpu_count() or 2))
    text_sess = ort.InferenceSession(
        str(model_dir / PREFILTER_FILES["text"][1]),
        sess_options=sess_opts,
        providers=["CPUExecutionProvider"],
    )
    input_names = {inp.name for inp in text_sess.get_inputs()}
    feeds: Dict[str, Any] = {"input_ids": input_ids}
    if "attention_mask" in input_names:
        feeds["attention_mask"] = attention_mask

    raw_outputs = text_sess.run(None, feeds)
    embeds = _l2_normalize(_pick_embedding_output(text_sess, raw_outputs))
    try:
        np.savez(cache_file, embeddings=embeds)
    except Exception:
        pass
    return embeds


def _get_vision_bundle(model_dir: Path) -> Dict[str, Any]:
    key = str(model_dir.resolve())
    with _SESSION_LOCK:
        cached = _CACHED_SESSIONS.get(key)
        if cached is not None:
            return cached

        import onnxruntime as ort

        prompts, meta = _build_prompt_catalog()
        text_embeds = _compute_text_embeddings(model_dir, prompts)

        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = max(1, min(6, os.cpu_count() or 4))
        vision_sess = ort.InferenceSession(
            str(model_dir / PREFILTER_FILES["vision"][1]),
            sess_options=sess_opts,
            providers=["CPUExecutionProvider"],
        )
        vision_input_name = vision_sess.get_inputs()[0].name
        bundle = {
            "vision_session": vision_sess,
            "vision_input_name": vision_input_name,
            "text_embeds": text_embeds,
            "prompt_meta": meta,
        }
        _CACHED_SESSIONS[key] = bundle
        return bundle


def _preprocess_pil_for_clip(pil_img) -> np.ndarray:
    """Resize + center-crop + normalize PIL RGB image to (3, 224, 224) float32 tensor."""
    from PIL import Image

    w, h = pil_img.size
    if w <= 0 or h <= 0:
        raise ValueError("Empty image dimensions.")
    resample = getattr(getattr(Image, "Resampling", Image), "BICUBIC", Image.BICUBIC)
    # Match CLIPFeatureExtractor: resize shortest edge to 224, then center crop 224x224
    if w < h:
        new_w = CLIP_IMAGE_SIZE
        new_h = max(CLIP_IMAGE_SIZE, int(round(h * (CLIP_IMAGE_SIZE / float(w)))))
    else:
        new_h = CLIP_IMAGE_SIZE
        new_w = max(CLIP_IMAGE_SIZE, int(round(w * (CLIP_IMAGE_SIZE / float(h)))))
    resized = pil_img.resize((new_w, new_h), resample)
    left = (new_w - CLIP_IMAGE_SIZE) // 2
    top = (new_h - CLIP_IMAGE_SIZE) // 2
    cropped = resized.crop((left, top, left + CLIP_IMAGE_SIZE, top + CLIP_IMAGE_SIZE))

    arr = np.asarray(cropped, dtype=np.float32) / 255.0  # (224, 224, 3)
    arr = np.transpose(arr, (2, 0, 1))  # (3, 224, 224)
    return (arr - CLIP_MEAN) / CLIP_STD


def _compute_sharpness_score(pil_img) -> float:
    """Fast OpenCV Laplacian variance sharpness score on a 320px thumbnail."""
    try:
        import cv2

        gray = np.asarray(pil_img.convert("L"), dtype=np.uint8)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        return float(round(lap.var(), 2))
    except Exception:
        return 100.0


def _dhash_hamming(hex_a: str, hex_b: str) -> int:
    if not hex_a or not hex_b or len(hex_a) != 16 or len(hex_b) != 16:
        return 999
    return (int(hex_a, 16) ^ int(hex_b, 16)).bit_count()


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exps = np.exp(shifted)
    return exps / np.maximum(np.sum(exps, axis=-1, keepdims=True), 1e-12)


def scan_folder_for_images(folder_path: str | Path, recursive: bool = True) -> List[Path]:
    """Collect supported survey photo paths from a directory, skipping hidden/backup folders."""
    root = Path(str(folder_path or "").strip())
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Folder not found: {root}")

    found: List[Path] = []
    iterator = root.rglob("*") if recursive else root.glob("*")
    for p in iterator:
        if not p.is_file():
            continue
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        if p.suffix.lower() in IMAGE_EXTENSIONS:
            found.append(p)
    found.sort(key=lambda p: str(p).lower())
    return found


def score_images_with_clip_onnx(
    pil_images: Sequence[Any],
    model_dir: Path,
    batch_size: int = 8,
) -> List[Dict[str, Any]]:
    """Run local ONNX CLIP classification using the custom trained ACIES head if available, else zero-shot."""
    if not pil_images:
        return []
    bundle = _get_vision_bundle(model_dir)
    vision_sess = bundle["vision_session"]
    input_name = bundle["vision_input_name"]
    custom = load_custom_classifier(model_dir)
    text_embeds = bundle["text_embeds"]  # (P, D)
    prompt_meta = bundle["prompt_meta"]

    results: List[Dict[str, Any]] = []
    for start in range(0, len(pil_images), max(1, batch_size)):
        batch_imgs = pil_images[start : start + batch_size]
        pixel_batch = np.stack([_preprocess_pil_for_clip(img) for img in batch_imgs], axis=0)
        raw_out = vision_sess.run(None, {input_name: pixel_batch})
        img_embeds = _l2_normalize(_pick_embedding_output(vision_sess, raw_out))  # (B, D)

        if custom is not None:
            logits = img_embeds @ custom["weights"].T + custom["bias"]  # (B, C)
            classes = custom["classes"]
            if custom.get("mode") == "multilabel_sigmoid":
                probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))
                is_panel_idx = custom["isPanelIdx"]
                for row_idx in range(probs.shape[0]):
                    row = probs[row_idx]
                    panel_prob = float(row[is_panel_idx])
                    tag_scores = {
                        classes[i]: float(row[i])
                        for i in range(len(classes))
                        if i != is_panel_idx
                    }
                    detected_tags = [t for t, sc in tag_scores.items() if sc >= 0.45]
                    has_structural = any(t in detected_tags for t in ("breakers", "directory", "main_breaker"))
                    if ("breakers" in detected_tags and "directory" in detected_tags) or (
                        len(detected_tags) >= 3 and has_structural
                    ):
                        best_bucket = "full_panel"
                        best_bucket_prob = panel_prob
                    elif detected_tags:
                        top_tag = max(detected_tags, key=lambda t: tag_scores[t])
                        best_bucket = TAG_TO_STUDIO_BUCKET.get(top_tag, "breakers")
                        best_bucket_prob = tag_scores[top_tag]
                    elif tag_scores:
                        top_tag, best_bucket_prob = max(tag_scores.items(), key=lambda kv: kv[1])
                        best_bucket = TAG_TO_STUDIO_BUCKET.get(top_tag, "breakers")
                    else:
                        best_bucket, best_bucket_prob = "breakers", panel_prob
                    results.append(
                        {
                            "panelScore": round(panel_prob, 4),
                            "suggestedBucket": best_bucket,
                            "bucketScore": round(best_bucket_prob, 4),
                            "detectedTags": detected_tags,
                            "topNegativeLabel": "Not Panel (ACIES Model)",
                            "topNegativeScore": round(1.0 - panel_prob, 4),
                            "classifierMode": "custom_multilabel",
                        }
                    )
                continue

            probs = _softmax(logits)
            not_idx = custom["notPanelIdx"]
            for row_idx in range(probs.shape[0]):
                row = probs[row_idx]
                not_prob = float(row[not_idx])
                panel_prob = max(0.0, min(1.0, 1.0 - not_prob))
                pos_pairs = [(classes[i], float(row[i])) for i in range(len(classes)) if i != not_idx]
                best_bucket, best_bucket_prob = (
                    max(pos_pairs, key=lambda kv: kv[1]) if pos_pairs else ("breakers", 0.0)
                )
                results.append(
                    {
                        "panelScore": round(panel_prob, 4),
                        "suggestedBucket": best_bucket,
                        "bucketScore": round(best_bucket_prob, 4),
                        "detectedTags": [best_bucket] if panel_prob >= 0.45 else [],
                        "topNegativeLabel": "Not Panel (ACIES Model)",
                        "topNegativeScore": round(not_prob, 4),
                        "classifierMode": "custom_trained",
                    }
                )
            continue

        cos_sims = img_embeds @ text_embeds.T  # (B, P)

        for row_idx in range(cos_sims.shape[0]):
            sims = cos_sims[row_idx]
            pos_bucket_sims: Dict[str, float] = {}
            neg_label_sims: Dict[str, float] = {}
            for p_idx, m in enumerate(prompt_meta):
                val = float(sims[p_idx])
                lbl = m["label"]
                if m["isPositive"]:
                    if lbl not in pos_bucket_sims or val > pos_bucket_sims[lbl]:
                        pos_bucket_sims[lbl] = val
                else:
                    if lbl not in neg_label_sims or val > neg_label_sims[lbl]:
                        neg_label_sims[lbl] = val

            best_bucket, best_pos_sim = (
                max(pos_bucket_sims.items(), key=lambda kv: kv[1])
                if pos_bucket_sims
                else ("breakers", 0.0)
            )
            best_neg_label, best_neg_sim = (
                max(neg_label_sims.items(), key=lambda kv: kv[1])
                if neg_label_sims
                else ("Non-panel", 0.0)
            )
            # Unbiased 2-way probability between best positive electrical match vs best negative match.
            # Temperature 40.0 maps a +0.05 CLIP cosine margin to ~0.88 and -0.05 to ~0.12.
            diff = (best_pos_sim - best_neg_sim) * 40.0
            diff = max(-30.0, min(30.0, diff))
            panel_prob = 1.0 / (1.0 + math.exp(-diff))

            # Softmax across the 4 positive buckets to pick the best bucket confidence
            bucket_keys = list(pos_bucket_sims.keys())
            bucket_vals = np.array([pos_bucket_sims[k] * 40.0 for k in bucket_keys], dtype=np.float32)
            bucket_probs = _softmax(bucket_vals)
            best_bucket_prob = float(bucket_probs[bucket_keys.index(best_bucket)]) if bucket_keys else 0.0

            studio_bucket = TAG_TO_STUDIO_BUCKET.get(best_bucket, "breakers")
            results.append(
                {
                    "panelScore": round(panel_prob, 4),
                    "suggestedBucket": studio_bucket,
                    "bucketScore": round(best_bucket_prob, 4),
                    "detectedTags": [best_bucket] if panel_prob >= 0.45 else [],
                    "topNegativeLabel": best_neg_label,
                    "topNegativeScore": round(1.0 - panel_prob, 4),
                }
            )
    return results


def prefilter_survey_photos(
    paths: Sequence[str | Path],
    *,
    app_data_dir: Optional[str | Path] = None,
    sensitivity: str = DEFAULT_SENSITIVITY,
    dedupe: bool = True,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    scorer_fn: Optional[Callable[[Sequence[Any]], List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Screen raw survey photos locally ($0 tokens) into kept panel candidates vs dropped photos.

    Returns ``kept`` (full source items ready for Studio buckets / gemini-decision-1),
    ``dropped`` (lightweight entries with thumbnail + reason so the user can rescue any shot),
    and ``stats`` (counts, elapsed ms, estimated token savings).
    """
    import panel_schedule_ai as psa

    started = time.perf_counter()
    threshold = SENSITIVITY_THRESHOLDS.get(str(sensitivity or "").lower(), SENSITIVITY_THRESHOLDS[DEFAULT_SENSITIVITY])

    resolved_paths: List[Path] = []
    warnings: List[str] = []
    for raw in paths or []:
        p = Path(str(raw or "").strip())
        if not p.exists():
            warnings.append(f"Not found: {p.name}")
            continue
        if p.is_dir():
            resolved_paths.extend(scan_folder_for_images(p, recursive=True))
        elif p.suffix.lower() in IMAGE_EXTENSIONS:
            resolved_paths.append(p)

    # Deduplicate identical filesystem paths while preserving order
    seen_paths: set[str] = set()
    unique_paths: List[Path] = []
    for p in resolved_paths:
        norm_p = str(p.resolve()).lower()
        if norm_p not in seen_paths:
            seen_paths.add(norm_p)
            unique_paths.append(p)

    if not unique_paths:
        raise ValueError("No supported photo files were found in the selected folder or files.")

    model_dir: Optional[Path] = None
    if scorer_fn is None:
        model_dir = ensure_prefilter_model(app_data_dir=app_data_dir, progress_callback=progress_callback)

    total = len(unique_paths)
    if progress_callback:
        progress_callback(
            {
                "stage": "scan",
                "progress": 5,
                "message": f"Reading EXIF timestamps & thumbnails for {total} photo(s)...",
            }
        )

    # Step 1: Read timestamps, thumbnails, dHash, sharpness & sort chronologically
    records: List[Dict[str, Any]] = []
    last_scan_emit = time.monotonic()
    for idx, p in enumerate(unique_paths):
        try:
            epoch, ts_label = psa._extract_photo_capture_timestamp(p)
            thumb_pil = psa._open_normalized_pil(p, max_edge=320)
            dhash = psa._compute_image_dhash(thumb_pil)
            sharpness = _compute_sharpness_score(thumb_pil)
            thumb_url = psa._pil_to_data_url(thumb_pil, fmt="JPEG", quality=76)
            records.append(
                {
                    "origIdx": idx,
                    "path": p,
                    "name": p.name,
                    "epoch": epoch if epoch is not None else float(idx),
                    "capturedAt": ts_label,
                    "thumbPil": thumb_pil,
                    "thumbDataUrl": thumb_url,
                    "dhash": dhash,
                    "sharpness": sharpness,
                }
            )
        except Exception as exc:
            warnings.append(f"Skipped unreadable photo {p.name}: {exc}")

        done_scan = idx + 1
        now = time.monotonic()
        if progress_callback and (now - last_scan_emit >= 0.35 or done_scan == total):
            last_scan_emit = now
            pct = int(5 + (done_scan / max(total, 1)) * 37)
            progress_callback(
                {
                    "stage": "scan",
                    "progress": pct,
                    "message": f"Reading photos & EXIF timestamps ({done_scan}/{total})...",
                }
            )

    if not records:
        raise RuntimeError("Could not read any photos from the selection.")

    records.sort(key=lambda r: (r["epoch"], r["origIdx"]))

    # Step 2: Run local zero-shot ONNX vision screening in batches
    scores: List[Dict[str, Any]] = []
    batch_size = 8
    total_readable = len(records)
    try:
        for start in range(0, total_readable, batch_size):
            batch_recs = records[start : start + batch_size]
            batch_pils = [r["thumbPil"] for r in batch_recs]
            if scorer_fn is not None:
                batch_scores = scorer_fn(batch_pils)
            else:
                batch_scores = score_images_with_clip_onnx(batch_pils, model_dir, batch_size=batch_size)
            scores.extend(batch_scores)
            done = min(total_readable, start + len(batch_recs))
            if progress_callback:
                pct = int(42 + (done / max(total_readable, 1)) * 53)
                progress_callback(
                    {
                        "stage": "score",
                        "progress": pct,
                        "message": f"Screening photos locally with ONNX CLIP ({done}/{total_readable})...",
                    }
                )
    finally:
        for r in records:
            try:
                r["thumbPil"].close()
            except Exception:
                pass
            r.pop("thumbPil", None)

    for rec, sc in zip(records, scores):
        rec.update(sc)

    # Step 3: Filter non-panel photos + burst duplicate pruning (keeping sharpest shot!)
    kept_candidates: List[Dict[str, Any]] = []
    dropped_items: List[Dict[str, Any]] = []
    non_panel_since_last_kept = 0
    last_kept_epoch: Optional[float] = None
    non_panel_dropped_count = 0
    duplicate_dropped_count = 0

    for rec in records:
        is_panel = rec["panelScore"] >= threshold
        if not is_panel:
            non_panel_since_last_kept += 1
            non_panel_dropped_count += 1
            dropped_items.append(
                {
                    "id": f"src_{uuid.uuid4().hex[:10]}",
                    "kind": "image",
                    "name": rec["name"],
                    "path": str(rec["path"]),
                    "pageIndex": None,
                    "pageCount": 1,
                    "pageLabel": rec["name"],
                    "selected": True,
                    "role": "ignore",
                    "hint": "",
                    "dhash": rec["dhash"],
                    "capturedAt": rec["capturedAt"],
                    "sharpness": rec["sharpness"],
                    "panelScore": rec["panelScore"],
                    "suggestedBucket": rec["suggestedBucket"],
                    "dropReason": f"{rec['topNegativeLabel']} ({int(round(rec['panelScore'] * 100))}% panel)",
                    "dropCategory": "non_panel",
                    "thumbDataUrl": rec["thumbDataUrl"],
                    "viewerDataUrl": "",
                }
            )
            continue

        # Candidate is panel-relevant; check if near-duplicate of a recently kept candidate
        if dedupe and rec["dhash"]:
            dup_match_idx = None
            for prev_idx in range(len(kept_candidates) - 1, max(-1, len(kept_candidates) - 8), -1):
                prev = kept_candidates[prev_idx]
                if _dhash_hamming(prev["dhash"], rec["dhash"]) <= DUPLICATE_DHASH_MAX_DISTANCE:
                    dup_match_idx = prev_idx
                    break
            if dup_match_idx is not None:
                prev = kept_candidates[dup_match_idx]
                duplicate_dropped_count += 1
                # Keep the sharper of the two near-duplicate shots!
                if rec["sharpness"] > prev["sharpness"] * 1.08:
                    # Swap: demote previous blurrier shot to dropped, promote this sharper shot
                    dropped_items.append(
                        {
                            "id": prev["id"],
                            "kind": "image",
                            "name": prev["name"],
                            "path": prev["path"],
                            "pageIndex": None,
                            "pageCount": 1,
                            "pageLabel": prev["pageLabel"],
                            "selected": True,
                            "role": "ignore",
                            "hint": "",
                            "dhash": prev["dhash"],
                            "capturedAt": prev["capturedAt"],
                            "sharpness": prev["sharpness"],
                            "panelScore": prev["panelScore"],
                            "suggestedBucket": prev["role"],
                            "dropReason": "Near duplicate (kept sharper shot)",
                            "dropCategory": "duplicate",
                            "thumbDataUrl": prev["thumbDataUrl"],
                            "viewerDataUrl": "",
                        }
                    )
                    kept_candidates[dup_match_idx] = {
                        **prev,
                        "id": f"src_{uuid.uuid4().hex[:10]}",
                        "name": rec["name"],
                        "path": str(rec["path"]),
                        "pageLabel": rec["name"],
                        "role": rec["suggestedBucket"],
                        "dhash": rec["dhash"],
                        "capturedAt": rec["capturedAt"],
                        "sharpness": rec["sharpness"],
                        "panelScore": rec["panelScore"],
                        "thumbDataUrl": rec["thumbDataUrl"],
                        "viewerDataUrl": "",
                    }
                    last_kept_epoch = rec["epoch"]
                    continue
                else:
                    dropped_items.append(
                        {
                            "id": f"src_{uuid.uuid4().hex[:10]}",
                            "kind": "image",
                            "name": rec["name"],
                            "path": str(rec["path"]),
                            "pageIndex": None,
                            "pageCount": 1,
                            "pageLabel": rec["name"],
                            "selected": True,
                            "role": "ignore",
                            "hint": "",
                            "dhash": rec["dhash"],
                            "capturedAt": rec["capturedAt"],
                            "sharpness": rec["sharpness"],
                            "panelScore": rec["panelScore"],
                            "suggestedBucket": rec["suggestedBucket"],
                            "dropReason": "Near duplicate (kept sharper shot)",
                            "dropCategory": "duplicate",
                            "thumbDataUrl": rec["thumbDataUrl"],
                            "viewerDataUrl": "",
                        }
                    )
                    continue

        gap_sec = int(round(max(0.0, rec["epoch"] - last_kept_epoch))) if last_kept_epoch is not None else 0
        kept_candidates.append(
            {
                "id": f"src_{uuid.uuid4().hex[:10]}",
                "kind": "image",
                "name": rec["name"],
                "path": str(rec["path"]),
                "isTemp": False,
                "pageIndex": None,
                "pageCount": 1,
                "pageLabel": rec["name"],
                "selected": True,
                "role": rec["suggestedBucket"],
                "hint": "",
                "dhash": rec["dhash"],
                "capturedAt": rec["capturedAt"],
                "sharpness": rec["sharpness"],
                "panelScore": rec["panelScore"],
                "detectedTags": list(rec.get("detectedTags") or []),
                "nonPanelGapBefore": non_panel_since_last_kept,
                "gapSecondsBefore": gap_sec,
                "thumbDataUrl": rec["thumbDataUrl"],
                "viewerDataUrl": "",
            }
        )
        non_panel_since_last_kept = 0
        last_kept_epoch = rec["epoch"]

    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    if progress_callback:
        progress_callback(
            {
                "stage": "done",
                "progress": 100,
                "message": f"Local pre-filter kept {len(kept_candidates)} of {total_readable} photos.",
            }
        )

    return {
        "model": PREFILTER_MODEL_ID,
        "threshold": threshold,
        "kept": kept_candidates,
        "dropped": dropped_items,
        "warnings": warnings,
        "stats": {
            "totalScanned": total_readable,
            "keptCount": len(kept_candidates),
            "droppedCount": len(dropped_items),
            "nonPanelDropped": non_panel_dropped_count,
            "duplicateDropped": duplicate_dropped_count,
            "elapsedMs": elapsed_ms,
            "estimatedTokensSaved": int(len(dropped_items) * 1200),
        },
    }
