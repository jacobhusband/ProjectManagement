"""Copy the Clean Drawings AutoCAD worker out of a pinned ACIES plugin release.

Clean Drawings loads AutoCADCommands.CleanCADCommands.dll into AutoCAD Core Console
with NETLOAD. Shipping that DLL (and the libraries beside it) inside the app means
users can run the tool without installing the AutoCAD plugin. The files are about
50 MB, so they are fetched at build time into scripts/CleanCAD-bin (git-ignored)
instead of being committed.

Run with no arguments to fill scripts/CleanCAD-bin; it does nothing when that folder
already holds the pinned release. Bump PLUGIN_VERSION and PLUGIN_SHA256 together when
Clean Drawings needs a newer worker.
"""
from __future__ import annotations

import hashlib
import io
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

PLUGIN_VERSION = "v0.4.0"
PLUGIN_URL = (
    "https://github.com/jacobhusband/ElectricalCommands/releases/download/"
    f"{PLUGIN_VERSION}/ElectricalCommands-{PLUGIN_VERSION}.zip"
)
PLUGIN_SHA256 = "cd7ae6ecbf04e2ecd7ae2573c8cd183c983b0b5f8e6c19f47262162447331222"
FRAMEWORKS = ("net48", "net8.0-windows")
WORKER_DLL = "AutoCADCommands.CleanCADCommands.dll"
# The bundle's other command DLLs are separate plugins Clean Drawings never loads.
OTHER_COMMAND_PREFIX = "autocadcommands."
VERSION_FILE = "version.txt"

DEFAULT_TARGET = Path(__file__).resolve().parent.parent / "scripts" / "CleanCAD-bin"


def worker_files(names):
    """Map each wanted zip entry to (framework, relative path inside that framework)."""
    picked = {}
    for name in names:
        if name.endswith("/"):
            continue
        parts = PurePosixPath(name).parts
        try:
            index = parts.index("Contents")
        except ValueError:
            continue
        rest = parts[index + 1:]
        if len(rest) < 2 or rest[0] not in FRAMEWORKS:
            continue
        framework, relative = rest[0], rest[1:]
        if any(part in ("", ".", "..") or ":" in part or "\\" in part for part in relative):
            raise ValueError(f"Unsafe path in plugin release: {name}")
        filename = relative[-1].lower()
        if len(relative) == 1 and not filename.endswith(".dll"):
            continue
        if filename.startswith(OTHER_COMMAND_PREFIX) and filename != WORKER_DLL.lower():
            continue
        picked[name] = (framework, PurePosixPath(*relative))
    return picked


def extract(archive_bytes, target):
    digest = hashlib.sha256(archive_bytes).hexdigest()
    if digest != PLUGIN_SHA256:
        raise ValueError(f"Plugin release checksum mismatch: expected {PLUGIN_SHA256}, got {digest}")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="CleanCAD-bin.", dir=target.parent))
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            picked = worker_files(archive.namelist())
            for name, (framework, relative) in picked.items():
                destination = staging / framework / Path(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, destination.open("wb") as out:
                    shutil.copyfileobj(source, out)
        for framework in FRAMEWORKS:
            if not (staging / framework / WORKER_DLL).is_file():
                raise ValueError(f"Plugin release {PLUGIN_VERSION} has no {framework}/{WORKER_DLL}")
        (staging / VERSION_FILE).write_text(PLUGIN_VERSION + "\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def is_current(target):
    target = Path(target)
    try:
        version = (target / VERSION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return version == PLUGIN_VERSION and all((target / fw / WORKER_DLL).is_file() for fw in FRAMEWORKS)


def main(argv):
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    if is_current(target):
        print(f"Clean Drawings worker {PLUGIN_VERSION} already in {target}")
        return 0
    print(f"Downloading Clean Drawings worker from {PLUGIN_URL}")
    with urllib.request.urlopen(PLUGIN_URL, timeout=300) as response:
        archive_bytes = response.read()
    extract(archive_bytes, target)
    print(f"Clean Drawings worker {PLUGIN_VERSION} copied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
