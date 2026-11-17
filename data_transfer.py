"""Versioned, validated data transfers. This module has no application startup effects."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile


FORMAT = "acies-project-management"
VERSION = 1
MAX_FILES = 100000
MAX_BYTES = 20 * 1024 ** 3
PRIVATE_SETTINGS = ("apiKey", "googleAuth", "microsoftAuth", "cloudSync")
RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
JSON_TYPES = {
    "tasks.json": list,
    "notes.json": dict,
    "settings.json": dict,
    "timesheets.json": dict,
    "templates.json": dict,
    "checklists.json": dict,
    "activity_history.json": (dict, list),
    "page_file_links.json": dict,
}


def _safe_name(name):
    parts = PurePosixPath(name).parts
    if (not parts or name != "/".join(parts) or "\\" in name
            or any(p in (".", "..") or any(c in p for c in '<>:"|?*') or p.endswith((".", " "))
                   or p.split(".")[0].casefold() in RESERVED_NAMES
                   or any(ord(c) < 32 for c in p) for p in parts)
            or PurePosixPath(name).is_absolute()):
        raise ValueError("The transfer contains an unsafe file path.")
    return parts


def _plain_path(path):
    path = Path(path)
    # Windows junctions and symlinks must not redirect a transfer outside its roots.
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError(f"Linked data folders are not supported: {item.name}")
    return path


def _snapshot_database(source, destination):
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("A database failed its integrity check.")


def _restore_database(source, destination):
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)


def _validate_json(name, data):
    value = json.loads(data)
    expected = JSON_TYPES.get(name)
    if expected and not isinstance(value, expected):
        raise ValueError(f"Invalid data structure in {name}.")
    if name == "tasks.json":
        if any(not isinstance(p, dict) or not (p.get("id") or p.get("name"))
               or ("deliverables" in p and not isinstance(p["deliverables"], list)) for p in value):
            raise ValueError("Invalid project records in tasks.json.")
    key = {"notes.json": "pages", "timesheets.json": "weeks",
           "templates.json": "templates", "checklists.json": "checklists"}.get(name)
    if key and key in value:
        expected_type = dict if key == "weeks" else list
        if not isinstance(value[key], expected_type):
            raise ValueError(f"Invalid {key} in {name}.")
    return value


def export_archive(destination, targets, directory_names, app_version="", source_root="", redact=True):
    """Snapshot managed files, including SQLite WAL contents, then atomically save a ZIP."""
    destination = Path(destination).resolve()
    for target in targets.values():
        target = _plain_path(target).resolve()
        if destination == target or target in destination.parents:
            raise ValueError("Choose an export location outside the app's managed data.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".acies-transfer-", suffix=".zip", dir=destination.parent)
    os.close(fd)
    try:
        with tempfile.TemporaryDirectory() as scratch, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            entries = {}
            total = 0

            def add(name, path):
                nonlocal total
                _safe_name(name)
                path = _plain_path(path)
                if name.endswith(".db") and "/" not in name:
                    snapshot = Path(scratch) / name
                    _snapshot_database(path, snapshot)
                    path = snapshot
                data = path.read_bytes()
                if name in JSON_TYPES:
                    value = _validate_json(name, data)
                    if name == "settings.json" and redact:
                        for key in PRIVATE_SETTINGS:
                            value.pop(key, None)
                        data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
                total += len(data)
                if len(entries) >= MAX_FILES or total > MAX_BYTES:
                    raise ValueError("The transfer exceeds the supported size.")
                entries[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                archive.writestr(name, data)

            for name, target in targets.items():
                path = _plain_path(target)
                if not path.exists():
                    continue
                if name in directory_names:
                    def unreadable(error):
                        raise error

                    for base, dirs, files in os.walk(path, followlinks=False, onerror=unreadable):
                        for child in dirs:
                            _plain_path(Path(base) / child)
                        for child in sorted(files):
                            item = Path(base) / child
                            add(f"{name}/{item.relative_to(path).as_posix()}", item)
                else:
                    add(name, path)
            manifest = {"format": FORMAT, "version": VERSION, "appVersion": app_version,
                        "exportedAt": datetime.now(timezone.utc).isoformat(),
                        "sourceRoot": str(source_root), "roots": sorted(targets), "files": entries}
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        with open(temporary, "r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return manifest
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def stage_archive(source, stage, targets, directory_names):
    """Validate the entire archive before any existing data can be changed."""
    stage = Path(stage)
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 1 or sum(i.file_size for i in infos) > MAX_BYTES:
            raise ValueError("The transfer exceeds the supported size.")
        names = [i.filename for i in infos]
        if len(names) != len(set(n.casefold() for n in names)) or "manifest.json" not in names:
            raise ValueError("The transfer has duplicate files or no manifest.")
        if archive.getinfo("manifest.json").file_size > 32 * 1024 ** 2:
            raise ValueError("The transfer manifest is too large.")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ValueError("Choose a supported ACIES data export ZIP.")
        roots = manifest.get("roots")
        entries = manifest.get("files")
        if (not isinstance(roots, list) or len(roots) != len(set(roots))
                or set(roots) != set(targets) or not isinstance(entries, dict)
                or set(names) != {"manifest.json", *entries}):
            raise ValueError("The transfer file list is incomplete or unsupported.")
        for info in infos:
            if info.filename == "manifest.json":
                continue
            parts = _safe_name(info.filename)
            if (parts[0] not in targets or (len(parts) > 1 and parts[0] not in directory_names)
                    or (len(parts) == 1 and parts[0] in directory_names)):
                raise ValueError("The transfer contains an unsupported file.")
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("The transfer contains an unsupported linked file.")
            record = entries[info.filename]
            data = archive.read(info)
            if (not isinstance(record, dict) or len(data) != record.get("size")
                    or hashlib.sha256(data).hexdigest() != record.get("sha256")):
                raise ValueError(f"The transfer is damaged: {info.filename}")
            if info.filename in JSON_TYPES:
                _validate_json(info.filename, data)
            output = stage.joinpath(*parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            if len(parts) == 1 and info.filename.endswith(".db"):
                with closing(sqlite3.connect(output.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
                    if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise ValueError(f"Invalid database: {info.filename}")
    return manifest


def _replace_file(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".acies-import-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            with open(source, "rb") as incoming:
                shutil.copyfileobj(incoming, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def restore_staged(stage, targets, directory_names, backup_root, app_version=""):
    """Keep a complete local recovery ZIP, then replace data with rollback on failure."""
    stage = Path(stage)
    for target in targets.values():
        _plain_path(target)
    backup = Path(backup_root) / f"before-import-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.zip"
    # This local recovery copy retains keys; portable exports omit them.
    export_archive(backup, targets, directory_names, app_version, redact=False)
    with tempfile.TemporaryDirectory(prefix="acies-rollback-") as rollback:
        stage_archive(backup, rollback, targets, directory_names)
        changed = []

        def install(name, root):
            incoming = Path(root) / name
            target = Path(targets[name])
            if name in directory_names:
                if target.exists():
                    shutil.rmtree(target)
                if incoming.exists():
                    shutil.copytree(incoming, target)
            elif incoming.exists():
                if name.endswith(".db"):
                    _restore_database(incoming, target)
                else:
                    _replace_file(incoming, target)
            else:
                for path in [target, *([Path(str(target) + ext) for ext in ("-wal", "-shm")] if name.endswith(".db") else [])]:
                    if path.exists():
                        path.unlink()

        try:
            for name in targets:
                changed.append(name)
                install(name, stage)
        except Exception as error:
            failures = []
            for name in reversed(changed):
                try:
                    install(name, rollback)
                except Exception as restore_error:
                    failures.append(str(restore_error))
            suffix = " Some files could not be restored automatically." if failures else " Previous data was restored."
            raise RuntimeError(f"Import failed.{suffix} Recovery copy: {backup}") from error
    return str(backup)
