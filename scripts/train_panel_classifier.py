"""Train a custom multi-label ACIES electrical-panel visual classifier on ONNX CLIP embeddings.

Why multi-label?
Real site survey photos frequently show combinations in one frame — e.g.
``panel_tag + breakers``, ``breakers + main_breaker``, or a full open panelboard
showing ``panel_tag + breakers + directory + main_breaker``.
Separating ``panel_tag`` (engraved placard / P-touch panel ID), ``nameplate``
(factory spec plate), and ``wiring_label`` (inside-door wiring diagram / SCCR / UL
label) gives CLIP clean, visually distinct concepts instead of conflating them.

This trainer reads labels from:
1. ``panel_dataset/labels.json`` (written by ``scripts/panel_photo_labeler.py``), where
   each image has zero or more tags from
   ``(panel_tag, nameplate, wiring_label, breakers, directory, main_breaker)``
   (empty tag list = ``not_panel``).
2. Any images manually placed into legacy subfolders:
   ``panel_tag/``, ``nameplate/``, ``wiring_label/``, ``breakers/``, ``directory/``,
   ``main_breaker/``, ``full_panel/`` (mapped to panel_tag+breakers+directory+main_breaker),
   and ``not_panel/`` (mapped to ``[]``).

Trains 7 independent L2-regularized binary logistic heads (pure NumPy, ~2s on CPU):
- ``is_panel``     : Dedicated binary Panel vs Not-Panel gate (used for Stage 1 filtering)
- ``panel_tag``    : Engraved phenolic panel name tags, Brady/P-touch stickers, Sharpie IDs
- ``nameplate``    : Factory rating/spec nameplate (Model/Catalog #, Bus Amps, Voltage, Phase)
- ``wiring_label`` : Inside-door Typical Wiring Diagram, SCCR / Series Rating, Lug/Torque & UL labels
- ``breakers``     : Physical branch circuit breakers
- ``directory``    : Printed or handwritten door circuit directory
- ``main_breaker`` : Main breaker handle / MLO compartment

Saves ``acies_panel_classifier.npz`` inside the local ONNX model cache so
Panel Schedule AI Studio automatically hot-reloads it immediately.

Usage:
    .venv\\Scripts\\python.exe scripts/train_panel_classifier.py
    .venv\\Scripts\\python.exe scripts/train_panel_classifier.py --dataset "C:/path/to/panel_dataset"
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import panel_photo_prefilter as pf
import panel_schedule_ai as psa

TAG_NAMES: Tuple[str, ...] = (
    "panel_tag",
    "nameplate",
    "wiring_label",
    "breakers",
    "directory",
    "main_breaker",
)
# Head 0 is the dedicated binary Panel vs Not-Panel gate; heads 1..6 are independent content tags.
HEAD_NAMES: Tuple[str, ...] = ("is_panel",) + TAG_NAMES
LEGACY_FOLDER_TO_TAGS: Dict[str, Tuple[str, ...]] = {
    "panel_tag": ("panel_tag",),
    "nameplate": ("nameplate",),
    "wiring_label": ("wiring_label",),
    "breakers": ("breakers",),
    "directory": ("directory",),
    "main_breaker": ("main_breaker",),
    "full_panel": ("panel_tag", "breakers", "directory", "main_breaker"),
    "not_panel": (),
}
L2_GRID = (0.0005, 0.002, 0.008, 0.03, 0.1)


def get_default_dataset_dir(app_data_dir: Optional[str | Path] = None) -> Path:
    if app_data_dir:
        return Path(app_data_dir) / "panel_dataset"
    return Path.home() / "Documents" / "ProjectManagementApp" / "panel_dataset"


def ensure_dataset_folders(dataset_dir: Path) -> Dict[str, Path]:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    images_dir = dataset_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    folders: Dict[str, Path] = {"images": images_dir}
    for name in LEGACY_FOLDER_TO_TAGS:
        d = dataset_dir / name
        d.mkdir(parents=True, exist_ok=True)
        folders[name] = d
    return folders


def _tags_to_head_vector(tags: Sequence[str]) -> np.ndarray:
    clean = {str(t).strip().lower() for t in tags if str(t).strip().lower() in TAG_NAMES}
    vec = np.zeros((len(HEAD_NAMES),), dtype=np.float32)
    if clean:
        vec[0] = 1.0  # is_panel
    for idx, tag in enumerate(TAG_NAMES, start=1):
        if tag in clean:
            vec[idx] = 1.0
    return vec


def collect_labeled_images(dataset_dir: Path) -> Tuple[List[Path], np.ndarray, Dict[str, int]]:
    """Collect multi-label training examples from labels.json + any legacy class folders."""
    paths: List[Path] = []
    targets: List[np.ndarray] = []
    seen_resolved: set[str] = set()
    counts: Dict[str, int] = {
        "total": 0,
        "panel_any": 0,
        "not_panel": 0,
        "multi_tag": 0,
        **{t: 0 for t in TAG_NAMES},
    }

    def _add_example(fp: Path, tags: Sequence[str]) -> None:
        if not fp.exists() or not fp.is_file():
            return
        key = str(fp.resolve()).lower()
        if key in seen_resolved:
            return
        seen_resolved.add(key)
        clean_tags = sorted({str(t).strip().lower() for t in tags if str(t).strip().lower() in TAG_NAMES})
        paths.append(fp)
        targets.append(_tags_to_head_vector(clean_tags))
        counts["total"] += 1
        if clean_tags:
            counts["panel_any"] += 1
            if len(clean_tags) > 1:
                counts["multi_tag"] += 1
            for t in clean_tags:
                counts[t] += 1
        else:
            counts["not_panel"] += 1

    # 1. Primary multi-label manifest: labels.json
    labels_json = dataset_dir / "labels.json"
    if labels_json.exists():
        try:
            raw = json.loads(labels_json.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for entry in raw.values():
                    if not isinstance(entry, dict):
                        continue
                    rel_or_abs = str(entry.get("file") or entry.get("dest") or "").strip()
                    if not rel_or_abs:
                        continue
                    fp = Path(rel_or_abs)
                    if not fp.is_absolute():
                        fp = dataset_dir / fp
                    tags = entry.get("tags")
                    if not isinstance(tags, list):
                        legacy_cls = str(entry.get("class") or "").strip().lower()
                        tags = list(LEGACY_FOLDER_TO_TAGS.get(legacy_cls, ()))
                    _add_example(fp, tags)
        except Exception:
            pass

    # 2. Legacy / manual folder structure (nameplate/, breakers/, directory/, main_breaker/, full_panel/, not_panel/)
    for folder_name, folder_tags in LEGACY_FOLDER_TO_TAGS.items():
        cls_dir = dataset_dir / folder_name
        if not cls_dir.exists() or not cls_dir.is_dir():
            continue
        for fp in pf.scan_folder_for_images(cls_dir, recursive=True):
            _add_example(fp, folder_tags)

    if not targets:
        return [], np.zeros((0, len(HEAD_NAMES)), dtype=np.float32), counts
    return paths, np.stack(targets, axis=0).astype(np.float32), counts


def _file_cache_key(path: Path) -> str:
    st = path.stat()
    return f"{str(path.resolve()).lower()}|{int(st.st_size)}|{int(st.st_mtime)}"


def extract_dataset_embeddings(
    paths: Sequence[Path],
    model_dir: Path,
    *,
    cache_path: Optional[Path] = None,
    batch_size: int = 16,
    progress_callback: Optional[Callable[[str, int], None]] = None,
) -> Tuple[np.ndarray, List[int]]:
    """Extract L2-normalized 512-dim CLIP vision embeddings with disk caching."""
    cached_map: Dict[str, np.ndarray] = {}
    if cache_path and cache_path.exists():
        try:
            loaded = np.load(cache_path, allow_pickle=False)
            keys = loaded["keys"].tolist()
            vecs = np.asarray(loaded["embeddings"], dtype=np.float32)
            for k, v in zip(keys, vecs):
                cached_map[str(k)] = v
        except Exception:
            cached_map = {}

    results: List[Optional[np.ndarray]] = [None] * len(paths)
    to_compute: List[Tuple[int, Path, str]] = []
    for idx, fp in enumerate(paths):
        try:
            ck = _file_cache_key(fp)
        except Exception:
            continue
        if ck in cached_map:
            results[idx] = cached_map[ck]
        else:
            to_compute.append((idx, fp, ck))

    if to_compute:
        bundle = pf._get_vision_bundle(model_dir)
        vision_sess = bundle["vision_session"]
        input_name = bundle["vision_input_name"]

        total_new = len(to_compute)
        for start in range(0, total_new, batch_size):
            chunk = to_compute[start : start + batch_size]
            valid_chunk: List[Tuple[int, str, np.ndarray]] = []
            for idx, fp, ck in chunk:
                try:
                    img = psa._open_normalized_pil(fp, max_edge=320)
                    try:
                        tensor = pf._preprocess_pil_for_clip(img)
                    finally:
                        img.close()
                    valid_chunk.append((idx, ck, tensor))
                except Exception:
                    continue
            if valid_chunk:
                pixel_batch = np.stack([item[2] for item in valid_chunk], axis=0)
                raw_out = vision_sess.run(None, {input_name: pixel_batch})
                embeds = pf._l2_normalize(pf._pick_embedding_output(vision_sess, raw_out))
                for row_i, (orig_idx, ck, _) in enumerate(valid_chunk):
                    vec = np.asarray(embeds[row_i], dtype=np.float32)
                    results[orig_idx] = vec
                    cached_map[ck] = vec

            if progress_callback:
                done = min(total_new, start + len(chunk))
                pct = int(round((done / max(total_new, 1)) * 75))
                progress_callback(f"Embedding new training photos ({done}/{total_new})...", pct)

        if cache_path and cached_map:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                all_keys = np.array(list(cached_map.keys()), dtype="<U512")
                all_vecs = np.stack([cached_map[k] for k in cached_map.keys()], axis=0).astype(np.float32)
                np.savez(cache_path, keys=all_keys, embeddings=all_vecs)
            except Exception:
                pass

    valid_indices: List[int] = []
    valid_vecs: List[np.ndarray] = []
    for idx, vec in enumerate(results):
        if vec is not None:
            valid_indices.append(idx)
            valid_vecs.append(vec)

    if not valid_vecs:
        return np.zeros((0, 512), dtype=np.float32), []
    return np.stack(valid_vecs, axis=0).astype(np.float32), valid_indices


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    clipped = np.clip(logits, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def fit_binary_logreg(
    X: np.ndarray,
    y_bin: np.ndarray,
    *,
    l2: float = 0.01,
    epochs: int = 320,
    lr: float = 0.16,
) -> Tuple[np.ndarray, float]:
    """Fit a class-balanced L2-regularized binary logistic regression head in pure NumPy."""
    n_samples, n_features = X.shape
    pos = float(np.sum(y_bin > 0.5))
    neg = float(n_samples - pos)
    if pos == 0:
        return np.zeros((n_features,), dtype=np.float32), -8.0
    if neg == 0:
        return np.zeros((n_features,), dtype=np.float32), 8.0

    pos_weight = min(4.0, max(0.35, neg / pos))
    sample_w = np.where(y_bin > 0.5, pos_weight, 1.0).astype(np.float64)
    sample_w /= np.sum(sample_w)

    X64 = X.astype(np.float64, copy=False)
    y64 = y_bin.astype(np.float64, copy=False)
    w = np.zeros((n_features,), dtype=np.float64)
    b = math.log(pos / neg)
    mw = np.zeros_like(w)
    vw = np.zeros_like(w)
    mb = 0.0
    vb = 0.0
    beta1, beta2, eps = 0.9, 0.999, 1e-8

    for t in range(1, epochs + 1):
        probs = _sigmoid(X64 @ w + b)
        diff = (probs - y64) * sample_w
        grad_w = X64.T @ diff + l2 * w
        grad_b = float(np.sum(diff))

        step_lr = max(lr * 0.05, lr * 0.5 * (1.0 + math.cos(math.pi * (t - 1) / max(epochs, 1))))
        mw = beta1 * mw + (1.0 - beta1) * grad_w
        vw = beta2 * vw + (1.0 - beta2) * (grad_w * grad_w)
        mb = beta1 * mb + (1.0 - beta1) * grad_b
        vb = beta2 * vb + (1.0 - beta2) * (grad_b * grad_b)

        w -= step_lr * (mw / (1.0 - beta1**t)) / (np.sqrt(vw / (1.0 - beta2**t)) + eps)
        b -= step_lr * (mb / (1.0 - beta1**t)) / (math.sqrt(vb / (1.0 - beta2**t)) + eps)

    return w.astype(np.float32), float(b)


def fit_multilabel_heads(
    X: np.ndarray,
    Y: np.ndarray,
    *,
    l2: float = 0.01,
    epochs: int = 320,
) -> Tuple[np.ndarray, np.ndarray]:
    """Fit independent sigmoid heads for ``HEAD_NAMES`` (is_panel + 4 content tags)."""
    n_heads = Y.shape[1]
    n_features = X.shape[1]
    W = np.zeros((n_heads, n_features), dtype=np.float32)
    b = np.zeros((n_heads,), dtype=np.float32)
    for h_idx in range(n_heads):
        w_h, b_h = fit_binary_logreg(X, Y[:, h_idx], l2=l2, epochs=epochs)
        W[h_idx] = w_h
        b[h_idx] = b_h
    return W, b


def _stratified_folds_binary(is_panel: np.ndarray, k: int = 5, seed: int = 42) -> List[np.ndarray]:
    rng = np.random.default_rng(seed)
    folds: List[List[int]] = [[] for _ in range(k)]
    for val in (0, 1):
        idxs = np.where((is_panel > 0.5) == bool(val))[0]
        rng.shuffle(idxs)
        for pos, idx in enumerate(idxs):
            folds[pos % k].append(int(idx))
    return [np.array(f, dtype=np.int64) for f in folds if f]


def evaluate_multilabel_predictions(Y_true: np.ndarray, P_pred: np.ndarray, threshold: float = 0.45) -> Dict[str, Any]:
    per_head: Dict[str, Dict[str, Any]] = {}
    tag_f1s: List[float] = []

    for h_idx, name in enumerate(HEAD_NAMES):
        yt = Y_true[:, h_idx] > 0.5
        yp = P_pred[:, h_idx] >= threshold
        tp = int(np.sum(yt & yp))
        fp = int(np.sum((~yt) & yp))
        fn = int(np.sum(yt & (~yp)))
        tn = int(np.sum((~yt) & (~yp)))
        support = tp + fn
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / support if support > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        per_head[name] = {
            "support": support,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
        }
        if name != "is_panel" and support > 0:
            tag_f1s.append(f1)

    panel_stats = per_head["is_panel"]
    macro_tag_f1 = float(np.mean(tag_f1s)) if tag_f1s else panel_stats["f1"]
    return {
        "panelPrecision": panel_stats["precision"],
        "panelRecall": panel_stats["recall"],
        "panelF1": panel_stats["f1"],
        "macroTagF1": round(macro_tag_f1, 4),
        "overallAccuracy": round(
            (panel_stats["tp"] + panel_stats["tn"]) / max(len(Y_true), 1), 4
        ),
        "binaryCounts": {
            "tp": panel_stats["tp"],
            "fp": panel_stats["fp"],
            "fn": panel_stats["fn"],
            "tn": panel_stats["tn"],
        },
        "perHead": per_head,
    }


def train_from_dataset(
    dataset_dir: Path,
    *,
    app_data_dir: Optional[str | Path] = None,
    output_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[str, int], None]] = None,
    embeddings_override: Optional[Tuple[np.ndarray, np.ndarray, Dict[str, int]]] = None,
) -> Dict[str, Any]:
    """Train & 5-fold cross-validate the multi-label ACIES panel classifier and save weights."""
    started = time.perf_counter()
    model_dir = pf.get_model_cache_dir(app_data_dir)
    dest = Path(output_path) if output_path else pf.get_custom_classifier_path(model_dir)

    if embeddings_override is not None:
        X, Y, counts = embeddings_override
    else:
        model_dir = pf.ensure_prefilter_model(app_data_dir=app_data_dir)
        paths, raw_Y, counts = collect_labeled_images(dataset_dir)
        if not paths:
            raise ValueError(
                f"No labeled photos found in {dataset_dir}. "
                "Use scripts/panel_photo_labeler.py to label survey photos first."
            )
        X, valid_indices = extract_dataset_embeddings(
            paths,
            model_dir,
            cache_path=dataset_dir / ".embed_cache.npz",
            progress_callback=progress_callback,
        )
        Y = raw_Y[valid_indices]

    pos_count = int(np.sum(Y[:, 0] > 0.5))
    neg_count = int(len(Y) - pos_count)
    if pos_count < 4 or neg_count < 4:
        raise ValueError(
            f"Need at least 4 panel photos and 4 not_panel photos to train "
            f"(currently {pos_count} panel, {neg_count} not_panel)."
        )

    n_samples = len(Y)
    n_folds = max(2, min(5, min(pos_count, neg_count)))
    folds = _stratified_folds_binary(Y[:, 0], k=n_folds, seed=42)

    if progress_callback:
        progress_callback(f"Running {n_folds}-fold cross-validation across {n_samples} photos...", 80)

    best_l2 = L2_GRID[2]
    best_score = -1.0
    best_metrics: Optional[Dict[str, Any]] = None

    for l2 in L2_GRID:
        oof_probs = np.zeros((n_samples, len(HEAD_NAMES)), dtype=np.float32)
        for fold_idx in range(len(folds)):
            val_idx = folds[fold_idx]
            train_mask = np.ones((n_samples,), dtype=bool)
            train_mask[val_idx] = False
            W_f, b_f = fit_multilabel_heads(X[train_mask], Y[train_mask], l2=l2)
            oof_probs[val_idx] = _sigmoid(X[val_idx] @ W_f.T + b_f)

        metrics = evaluate_multilabel_predictions(Y, oof_probs)
        composite = 0.60 * metrics["panelF1"] + 0.40 * metrics["macroTagF1"]
        if composite > best_score:
            best_score = composite
            best_l2 = l2
            best_metrics = metrics

    if progress_callback:
        progress_callback("Fitting final multi-label model on 100% of labeled dataset...", 92)

    W_final, b_final = fit_multilabel_heads(X, Y, l2=best_l2, epochs=420)
    elapsed_sec = round(time.perf_counter() - started, 2)

    metadata = {
        "version": "2.0-multilabel",
        "mode": "multilabel_sigmoid",
        "backboneModelId": pf.PREFILTER_MODEL_ID,
        "trainedAt": datetime.now().isoformat(timespec="seconds"),
        "sampleCount": int(n_samples),
        "positiveCount": pos_count,
        "negativeCount": neg_count,
        "classCounts": counts,
        "heads": list(HEAD_NAMES),
        "tags": list(TAG_NAMES),
        "bestL2": best_l2,
        "cvFolds": len(folds),
        "metrics": best_metrics or {},
        "elapsedSec": elapsed_sec,
    }

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(f"{dest.stem}.tmp.npz")
    np.savez(
        tmp_path,
        weights=W_final,
        bias=b_final,
        classes=np.array(HEAD_NAMES, dtype="<U32"),
        mode=np.array("multilabel_sigmoid", dtype="<U32"),
        metadata_json=np.array(json.dumps(metadata), dtype="<U16384"),
    )
    os.replace(tmp_path, dest)
    pf.invalidate_custom_classifier_cache()

    if progress_callback:
        progress_callback("Custom multi-label ACIES panel classifier saved and active!", 100)

    return {
        "outputPath": str(dest),
        "metadata": metadata,
    }


def _print_report(result: Dict[str, Any]) -> None:
    meta = result["metadata"]
    m = meta.get("metrics") or {}
    print("\n=== ACIES Multi-Label Panel Photo Classifier Trained ===")
    print(f"Saved weights : {result['outputPath']}")
    print(f"Samples       : {meta['sampleCount']} ({meta['classCounts']})")
    print(f"Best L2       : {meta['bestL2']} ({meta['cvFolds']}-fold CV, {meta['elapsedSec']}s)")
    print(
        f"Panel vs Other: Precision {m.get('panelPrecision', 0) * 100:.1f}% | "
        f"Recall {m.get('panelRecall', 0) * 100:.1f}% | F1 {m.get('panelF1', 0) * 100:.1f}%"
    )
    print(f"Macro Tag F1  : {m.get('macroTagF1', 0) * 100:.1f}%")
    print("\nPer-head metrics:")
    for name, stats in (m.get("perHead") or {}).items():
        print(
            f"  {name:14s} (n={stats['support']:3d})  "
            f"P={stats['precision']*100:5.1f}%  R={stats['recall']*100:5.1f}%  F1={stats['f1']*100:5.1f}%"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Train custom multi-label ACIES panel photo classifier.")
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(get_default_dataset_dir()),
        help="Path to dataset directory (uses labels.json and/or legacy class folders).",
    )
    parser.add_argument("--output", type=str, default="", help="Optional custom output .npz path.")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    ensure_dataset_folders(dataset_dir)
    result = train_from_dataset(
        dataset_dir,
        output_path=Path(args.output) if args.output else None,
        progress_callback=lambda msg, pct: print(f"[{pct:3d}%] {msg}"),
    )
    _print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
