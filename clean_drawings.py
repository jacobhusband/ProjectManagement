"""Headless cleanup orchestration. Originals are read/copied, never opened for saving."""
from datetime import datetime
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import uuid

import fitz
from clean_review import compare_sets

_run_lock = threading.Lock()


def _titleblock_name(path):
    return bool(re.search(r'(?:^|[^a-z0-9])(?:tb|tblk|tblock|titleblock|title|border)(?:$|[^a-z0-9])', Path(path).stem, re.IGNORECASE))


def _rank_titleblocks(result):
    detected = set(result.get('detectedTitleblocks', []))
    likely = [p for p in result['titleblocks'] if p in detected and _titleblock_name(p)]
    result['recommendedTitleblock'] = likely[0] if len(likely) == 1 else None
    result['titleblocks'].sort(key=lambda p: (not (p in detected and _titleblock_name(p)), p not in detected, not _titleblock_name(p), p.casefold()))


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def discover(project, notify=lambda message: None):
    notify('Finding electrical drawings and titleblock candidates…')
    root = Path(project).resolve(strict=True)
    electrical = next((p for p in root.iterdir() if p.is_dir() and p.name.lower() == 'electrical'), None)
    xrefs = [p for p in root.iterdir() if p.is_dir() and p.name.lower() in ('xref', 'xrefs')]
    drawings = sorted(p for p in electrical.glob('*') if p.is_file() and p.suffix.lower() == '.dwg') if electrical else []
    candidates = sorted(p for folder in xrefs for p in folder.rglob('*')
                        if p.is_file() and p.suffix.lower() == '.dwg' and _inside(p, root))
    candidates.sort(key=lambda p: (not _titleblock_name(p), str(p)))
    pdfs = []
    notify('Finding published PDFs and checksets…')
    for folder in [root / 'PDF', (electrical / 'Checkset') if electrical else root / 'Electrical' / 'Checkset']:
        if folder.is_dir():
            pdfs.extend(p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() == '.pdf' and _inside(p, root))
    sizes = []
    for pdf in sorted(pdfs, key=lambda p: p.stat().st_mtime, reverse=True)[:25]:
        notify(f'Reading PDF sheet sizes: {pdf.name}')
        try:
            if pdf.stat().st_size > 150 * 1024 * 1024:
                continue
            with fitz.open(pdf) as doc:
                seen = set()
                for index in range(min(len(doc), 100)):
                    rect = doc[index].rect  # Includes page rotation; preserve landscape/portrait.
                    width, height = round(rect.width / 72, 3), round(rect.height / 72, 3)
                    short, long = sorted((width, height))
                    if not any(abs(short - a) <= 0.5 and abs(long - b) <= 0.5
                               for a, b in ((22, 34), (24, 36), (30, 42), (36, 48))):
                        continue
                    if (width, height) in seen:
                        continue
                    seen.add((width, height))
                    sizes.append({'pdf': str(pdf.relative_to(root)), 'page': index + 1,
                                  'width': width, 'height': height})
        except Exception:
            continue
    return {'project': str(root), 'drawings': [str(p.relative_to(root)) for p in drawings],
            'titleblocks': [str(p.relative_to(root)) for p in candidates], 'sizes': sizes}


def plugin_for(acad):
    acad = Path(acad)
    if acad.name.lower() != 'accoreconsole.exe' or not acad.is_file():
        raise ValueError('Select an installed AutoCAD Core Console in settings.')
    # AutoCAD 2025+ uses .NET 8; earlier supported releases use .NET Framework.
    import re
    match = re.search(r'20\d{2}', str(acad.parent))
    if not match:
        raise ValueError('Cannot determine the AutoCAD release from its installation path.')
    framework = 'net8.0-windows' if int(match.group()) >= 2025 else 'net48'
    dll = Path(os.environ.get('APPDATA', '')) / 'Autodesk' / 'ApplicationPlugins' / 'ElectricalCommands.CleanCADCommands.bundle' / 'Contents' / framework / 'AutoCADCommands.CleanCADCommands.dll'
    if not dll.is_file():
        raise FileNotFoundError('Install the updated CleanCADCommands plugin before running Clean Drawings.')
    return dll


def preview(project, acad, notify=lambda message: None):
    """Read actual paper-space references before asking the user to choose."""
    result = discover(project, notify=notify)
    if not result['drawings'] or not result['titleblocks']:
        return result
    root = Path(result['project'])
    workspace = Path(tempfile.mkdtemp(prefix='acies-clean-preview-'))
    try:
        seed = workspace / 'seed.dwg'
        shutil.copy2(root / result['drawings'][0], seed)
        notify(f'Inspecting paper-space titleblock references in {len(result["drawings"])} drawing(s)…')
        scan = run_worker(acad, plugin_for(acad), seed,
                          {'Operation': 'scan', 'Files': [str(root / p) for p in result['drawings']],
                           'Catalog': [str(root / p) for p in result['titleblocks']]}, workspace, notify=notify)
    except Exception as exc:
        raise RuntimeError(f'{exc}\nInspection logs retained at: {workspace}') from exc
    else:
        try:
            shutil.rmtree(workspace)
        except OSError:
            result['inspectionWarning'] = f'Inspection files could not be removed: {workspace}'
    detected = {str(Path(p).resolve()).casefold() for p in scan.get('titleblocks', [])}
    result['detectedTitleblocks'] = [p for p in result['titleblocks'] if str((root / p).resolve()).casefold() in detected]
    _rank_titleblocks(result)
    result['media'] = scan.get('media', [])
    return result


def run_worker(acad, dll, drawing, job, workspace, timeout=300, notify=lambda message: None):
    token = uuid.uuid4().hex
    folder = Path(workspace) / 'jobs' / token
    folder.mkdir(parents=True)
    request, result = folder / 'request.json', folder / 'result.json'
    job = dict(job, ResultPath=str(result))
    request.write_text(json.dumps(job), encoding='utf-8')
    script = folder / 'run.scr'
    # Paths are SCR arguments, not shell code. Reject line/quote injection.
    if any(c in str(dll) for c in '\r\n"'):
        raise ValueError('Invalid plugin path.')
    script.write_text('(setq aciesCleanSecure (getvar "SECURELOAD"))\n'
                      '(setvar "SECURELOAD" 0)\n_.NETLOAD\n"' + str(dll) + '"\n'
                      '(setvar "SECURELOAD" aciesCleanSecure)\n'
                      'ACIESCLEANJOB\n_.QUIT\n_Y\n', encoding='utf-8')
    env = dict(os.environ, ACIES_CLEAN_JOB=str(request))
    with (folder / 'worker.log').open('wb') as log:
        process = subprocess.Popen([str(acad), '/i', str(drawing), '/s', str(script), '/l', 'en-US'],
                                   cwd=str(folder), env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = time.monotonic()
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                process.kill()
                process.wait()
                raise RuntimeError(f'AutoCAD worker timed out; log: {folder / "worker.log"}')
            try:
                code = process.wait(timeout=min(5, remaining))
                break
            except subprocess.TimeoutExpired:
                elapsed = int(time.monotonic() - started)
                stage = {'scan': 'reference inspection', 'prepare': 'reference preparation',
                         'validate-titleblock': 'titleblock boundary check',
                         'plot-review': 'review PDF plotting', 'remove-titleblock-marks': 'titleblock stamp/signature removal',
                         'embed-media': 'PDF and image conversion', 'verify-media': 'embedded content validation',
                         'titleblock': 'titleblock cleanup', 'sheet': 'sheet cleanup',
                         'verify': 'saved drawing validation', 'strip-proxies': 'proxy object removal',
                         'verify-proxies': 'proxy removal validation'}.get(job['Operation'], job['Operation'])
                notify(f'AutoCAD {stage}: running ({elapsed}s elapsed)…')
    if not result.is_file():
        raise RuntimeError(f'Worker returned no result (exit {code}). Update the plugin; log: {folder / "worker.log"}')
    response = json.loads(result.read_text(encoding='utf-8-sig'))
    if code != 0 or not response.get('success'):
        raise RuntimeError(response.get('error') or f'Worker exited with code {code}; log: {folder / "worker.log"}')
    return response.get('details', {})


def _selected(root, relative):
    path = (root / relative).resolve(strict=True)
    if not _inside(path, root) or path.suffix.lower() != '.dwg':
        raise ValueError('Select a DWG inside the project.')
    return path


def _canonicalize_scan(scan):
    """Use one filesystem identity for mapped drives, UNC paths and case aliases.

    Keep Path fields verbatim: the CAD worker uses those to detect edits to the
    saved references. Only graph identities (Owner/Resolved/files) are normalized.
    PDF/image attachments whose files no longer exist display nothing in AutoCAD;
    they move to missingMedia so the worker removes the broken reference instead.
    """
    cache = {}
    identities = {}
    def canonical(value):
        key = os.path.normcase(value)
        if key not in cache:
            resolved = str(Path(value).resolve(strict=True))
            cache[key] = identities.setdefault(os.path.normcase(resolved), resolved)
        return cache[key]

    result = dict(scan)
    result['files'] = list(dict.fromkeys(canonical(p) for p in scan['files']))
    missing = []
    for field, identity in (('references', 'Name'), ('pdfs', 'Handle'), ('images', 'Handle')):
        records = {}
        for original in scan.get(field, []):
            try:
                resolved = canonical(original['Resolved'])
            except FileNotFoundError:
                # Missing XREFs already stop the scan; only attachments can be absent here.
                if field == 'references':
                    raise
                missing.append(dict(original, Owner=canonical(original['Owner']), Kind='PDF' if field == 'pdfs' else 'image'))
                continue
            record = dict(original, Owner=canonical(original['Owner']), Resolved=resolved)
            key = (record['Owner'], record[identity].casefold())
            if key in records and record != records[key]:
                raise RuntimeError(f'Conflicting {field} discovered through alternate paths: {record["Owner"]}')
            records[key] = record
        result[field] = list(records.values())
    result['missingMedia'] = missing
    result['titleblocks'] = list(dict.fromkeys(canonical(p) for p in scan.get('titleblocks', [])))
    result['proxies'] = [dict(record, File=canonical(record['File'])) for record in scan.get('proxies', [])]
    return result


def run(project, selection, acad, notify=lambda message: None, worker=run_worker, dll=None):
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError('A Clean Drawings job is already running.')
    workspace = None
    if worker is run_worker:
        def worker(acad, dll, drawing, job, workspace):
            return run_worker(acad, dll, drawing, job, workspace, notify=notify)
    try:
        root = Path(project).resolve(strict=True)
        titleblock = _selected(root, selection['titleblock'])
        drawings = list(dict.fromkeys(_selected(root, p) for p in selection['drawings']))
        if not drawings or titleblock in drawings:
            raise ValueError('Select electrical drawings separately from the titleblock.')
        width, height = float(selection['width']), float(selection['height'])
        if not all(math.isfinite(v) and 0 < v <= 1000 for v in (width, height)):
            raise ValueError('Enter valid sheet dimensions in CAD units.')
        dll = dll or plugin_for(acad)
        workspace = Path(tempfile.mkdtemp(prefix='acies-clean-'))
        seed = workspace / 'seed.dwg'
        shutil.copy2(titleblock, seed)
        seed.chmod(stat.S_IREAD | stat.S_IWRITE)
        notify(f'Checking titleblock geometry and boundary: {titleblock.name}')
        worker(acad, dll, seed, {'Operation': 'validate-titleblock', 'Width': width, 'Height': height}, workspace)
        notify('Inspecting drawings and required XREFs…')
        catalog = [str(root / p) for p in discover(root)['titleblocks']]
        scan = worker(acad, dll, seed, {'Operation': 'scan', 'Files': [str(titleblock), *map(str, drawings)], 'Catalog': catalog}, workspace)
        if scan.get('media'):
            raise RuntimeError('Headless embedding is not supported for these attachment types. No drawings were cleaned.\n' + '\n'.join(scan['media'][:12]))
        scan = _canonicalize_scan(scan)
        missing_media = scan['missingMedia']
        for record in missing_media:
            notify(f'Missing {record["Kind"]} will be removed: {record["Path"]} ({Path(record["Owner"]).name})')
        copies = {}
        fingerprints = {}
        media_copies = {}
        for kind, records in (('PDF', scan.get('pdfs', [])), ('image', scan.get('images', []))):
            for record in records:
                source = Path(record['Resolved']).resolve(strict=True)
                if str(source) in media_copies:
                    continue
                notify(f'Staging {kind}: {source.name}')
                target = workspace / 'media' / hashlib.sha256(str(source).encode()).hexdigest()[:12] / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                target.chmod(stat.S_IREAD | stat.S_IWRITE)
                fingerprints[str(source)] = _file_hash(target)
                if kind == 'PDF':
                    # PDFIMPORT omits annotations, so bake markups and form entries into the staged
                    # copy's page content. Layers and passwords have no faithful conversion: refuse.
                    baked = target.with_name(target.stem + '.baked.pdf')
                    with fitz.open(target) as document:
                        if document.needs_pass or document.get_ocgs():
                            raise RuntimeError(f'PDF contains optional layers or requires a password. Flatten a working PDF before cleanup: {source}')
                        if any(page.first_annot or page.first_widget for page in document):
                            notify(f'Flattening PDF markups and form fields in the working copy: {source.name}')
                            document.bake()
                            document.save(baked, garbage=3, deflate=True)
                    if baked.exists():
                        os.replace(baked, target)
                media_copies[str(source)] = str(target)
        def asset_map(records):
            return {record['Resolved']: media_copies[str(Path(record['Resolved']).resolve(strict=True))] for record in records}
        notify(f'Copying {len(scan["files"])} drawing dependencies to local working storage…')
        for source in scan['files']:
            path = Path(source).resolve(strict=True)
            relative = path.relative_to(root) if _inside(path, root) else Path('Dependencies') / hashlib.sha256(str(path).encode()).hexdigest()[:12] / path.name
            target = workspace / 'project' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            target.chmod(stat.S_IREAD | stat.S_IWRITE)
            fingerprints[str(path)] = _file_hash(target)
            copies[str(path)] = str(target)
        notify('Redirecting references to the local working copies…')
        worker(acad, dll, seed, {'Operation': 'prepare', 'Copies': copies, 'References': scan['references'],
                              'Pdfs': scan.get('pdfs', []), 'PdfCopies': asset_map(scan.get('pdfs', [])),
                              'Images': scan.get('images', []), 'ImageCopies': asset_map(scan.get('images', []))}, workspace)
        def plot_set(label, paths, layout_source=None, freeze_revision_layers=False):
            records = []
            for index, (source, drawing) in enumerate(paths, 1):
                relative = str(drawing.relative_to(root))
                notify(f'Plotting {label} {index} of {len(paths)}: {drawing.name}')
                job = {'Operation': 'plot-review', 'Output': str(workspace / f'{label}-{index}'), 'Width': width, 'Height': height}
                if layout_source is not None:
                    job['Layouts'] = [r['layout'] for r in layout_source if r['drawing'] == relative]
                if freeze_revision_layers:
                    job['FreezeRevisionLayers'] = True
                plotted = worker(acad, dll, source, job, workspace)
                for page in plotted['pages']:
                    records.append(dict(page, drawing=relative, profile=plotted.get('profile')))
            return records
        # Convert attachments before the Original plot: headless plotting omits raster
        # images, so plotting first would show converted logos as unexpected changes.
        media_results = []
        owners = {record['Owner'] for record in scan.get('pdfs', []) + scan.get('images', []) + missing_media}
        for index, owner in enumerate(sorted(owners), 1):
            notify(f'Converting PDF/image attachments {index} of {len(owners)}: {Path(owner).name}')
            staged = Path(copies[owner])
            converted = workspace / (uuid.uuid4().hex + '.dwg')
            counts = worker(acad, dll, staged, {'Operation': 'embed-media', 'Output': str(converted),
                                                'MissingMedia': [r for r in missing_media if r['Owner'] == owner]}, workspace)
            notify(f'Validating embedded content: {Path(owner).name}')
            if worker(acad, dll, converted, {'Operation': 'verify-media'}, workspace) != counts:
                raise RuntimeError(f'Embedded content changed after saving and reopening: {owner}')
            shutil.copy2(converted, staged)
            media_results.append({'drawing': owner, 'validation': counts})
        original_pdfs = plot_set('Original', [(Path(copies[str(d)]), d) for d in drawings])
        staged_titleblock = Path(copies[str(titleblock)])
        notify('Removing stamps and signatures from the staged titleblock…')
        unmarked = workspace / 'titleblock-without-marks.dwg'
        mark_removal = worker(acad, dll, staged_titleblock, {'Operation': 'remove-titleblock-marks', 'Output': str(unmarked)}, workspace)
        shutil.copy2(unmarked, staged_titleblock)
        # Sheet cleanup freezes revision cloud/delta layers on purpose; so does the reference.
        reference_pdfs = plot_set('Reference', [(Path(copies[str(d)]), d) for d in drawings], original_pdfs,
                                  freeze_revision_layers=True)
        # Core Console cannot bind an XREF holding add-on objects it has no enabler for
        # (Express Tools ARCTEXT, Civil 3D settings). Strip them from the staged XREF copies
        # after the reference plots, so the comparison checks that nothing visible changed.
        proxy_removal = []
        selected = {str(d) for d in drawings}
        for record in scan['proxies']:
            if record['File'] in selected:
                continue
            staged = Path(copies[record['File']])
            notify(f'Removing add-on proxy objects that block binding: {staged.name}')
            stripped = workspace / (uuid.uuid4().hex + '.dwg')
            removed = worker(acad, dll, staged, {'Operation': 'strip-proxies', 'Output': str(stripped)}, workspace)
            if worker(acad, dll, stripped, {'Operation': 'verify-proxies'}, workspace) != {'proxyEntities': 0, 'proxyObjects': 0}:
                raise RuntimeError(f'Proxy objects remained after saving and reopening: {record["File"]}')
            shutil.copy2(stripped, staged)
            proxy_removal.append(dict(removed, drawing=record['File']))
        output_root = workspace / 'outputs'
        output_root.mkdir()
        cleaned_titleblock = output_root / (uuid.uuid4().hex + '.dwg')
        notify('Cleaning the titleblock…')
        title_result = worker(acad, dll, staged_titleblock, {'Operation': 'titleblock', 'Width': width, 'Height': height, 'Output': str(cleaned_titleblock)}, workspace)
        notify('Validating the saved titleblock…')
        reopened = worker(acad, dll, cleaned_titleblock, {'Operation': 'verify'}, workspace)
        if reopened != title_result:
            raise RuntimeError('Titleblock entity counts changed after saving and reopening.')
        shutil.copy2(cleaned_titleblock, staged_titleblock)
        results = []
        outputs = [(staged_titleblock, titleblock.relative_to(root))]
        for index, drawing in enumerate(drawings, 1):
            notify(f'Cleaning drawing {index} of {len(drawings)}: {drawing.name}')
            staged = Path(copies[str(drawing)])
            output = output_root / (uuid.uuid4().hex + '.dwg')
            counts = worker(acad, dll, staged, {'Operation': 'sheet', 'Titleblock': str(staged_titleblock),
                                              'Width': width, 'Height': height, 'Output': str(output)}, workspace)
            notify(f'Validating drawing {index} of {len(drawings)}: {drawing.name}')
            reopened = worker(acad, dll, output, {'Operation': 'verify'}, workspace)
            if reopened != counts:
                raise RuntimeError(f'Entity counts changed after saving and reopening {drawing.name}.')
            outputs.append((output, drawing.relative_to(root)))
            results.append({'drawing': str(drawing.relative_to(root)), 'validation': reopened})
        cleaned_pdfs = plot_set('Cleaned', [(path, root / relative) for path, relative in outputs[1:]], original_pdfs)
        notify('Comparing original and cleaned PDFs, accounting for stamp/signature and revision cloud/delta removal…')
        review_directory = workspace / 'Review'
        comparison = compare_sets(original_pdfs, reference_pdfs, cleaned_pdfs, review_directory, notify=notify)
        needs_review = comparison['status'] == 'review_required'
        outputs.extend((file, Path('Review') / file.name) for file in sorted(review_directory.iterdir()) if file.is_file())
        notify('Checking source versions and delivering validated drawings…')
        for source, digest in fingerprints.items():
            if _file_hash(source) != digest:
                raise RuntimeError(f'Source changed during processing. Run again: {source}')
        report = {'status': 'review_required' if needs_review else 'success', 'selection': selection, 'drawings': results, 'mediaConversions': media_results,
                  'missingMediaRemoved': [{'drawing': r['Owner'], 'kind': r['Kind'], 'path': r['Path'], 'handle': r['Handle']} for r in missing_media],
                  'titleblockMarkRemoval': mark_removal, 'proxyRemoval': proxy_removal, 'comparison': comparison,
                  'titleblockValidation': title_result, 'sourceHashes': fingerprints,
                  'limitations': ['PDF pages import as native CAD objects; supported raster pixels become native solids.',
                                  'PDF markups and form fields are flattened into the imported page content.',
                                  'Custom PDF clips/adjustments, PDF layers, complex images, other underlays and linked OLE remain unsupported.',
                                  'Boundary intersection uses conservative entity bounds.',
                                  'Image colors are snapped to within 16/255 per channel; partly transparent image edges are blended over white paper.',
                                  'PDF comparison uses Layout at 1:1 inches, zero offset, 510-monochrome.ctb, 144 DPI and a 24/255 channel tolerance; it is not proof of engineering equivalence.',
                                  'Original plots are made after PDF/image conversion (headless plotting omits raster images), so the comparison checks cleanup, not the conversion itself.',
                                  'Add-on proxy objects in XREFs (e.g. Express Tools ARCTEXT, Civil 3D settings) are removed before binding: unused blocks holding them are purged, others become their stored proxy graphics.']}
        destination_root = root / 'Cleaned CAD'
        if not _inside(destination_root, root):
            raise RuntimeError('Cleaned CAD resolves outside the project directory.')
        destination_root.mkdir(exist_ok=True)
        stamp = datetime.now().strftime('%Y-%m-%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
        if needs_review:
            stamp += '_REVIEW_REQUIRED'
        pending = destination_root / ('.incomplete-' + stamp)
        pending.mkdir()
        for source, relative in outputs:
            destination = pending / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if _file_hash(source) != _file_hash(destination):
                raise RuntimeError(f'Output copy verification failed: {destination}')
        (pending / 'cleanup-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        destination = destination_root / stamp
        pending.rename(destination)
        # Remove only the unique local directory created by this invocation.
        cleanup_warning = ''
        media_warning = ''
        if missing_media:
            names = sorted({f'{Path(r["Owner"]).name}: {Path(r["Path"]).name}' for r in missing_media})
            media_warning = (f'Removed {len(missing_media)} broken PDF/image attachment(s) whose files are missing '
                             '(AutoCAD shows nothing for them in the originals): ' + '; '.join(names[:6])
                             + (f'; and {len(names) - 6} more' if len(names) > 6 else '') + '.')
        try:
            shutil.rmtree(workspace)
            workspace = None
        except OSError:
            cleanup_warning = f'Drawings delivered successfully. Temporary files could not be removed: {workspace}'
        return {'status': 'success', 'output': str(destination), 'count': len(drawings), 'cleanupWarning': cleanup_warning, 'mediaWarning': media_warning,
                'comparisonWarning': 'Review required: plotted differences remain beyond stamp/signature and revision cloud/delta removal. Open Review/Comparison.pdf before sharing these drawings.' if needs_review else '',
                'comparisonStatus': comparison['status']}
    except Exception as exc:
        raise RuntimeError(str(exc) + (f'\nWorking files and logs retained at: {workspace}' if workspace else '')) from exc
    finally:
        _run_lock.release()
