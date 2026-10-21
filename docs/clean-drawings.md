# Clean Drawings

Launch **Clean Drawings** from the Workroom or General tools with a project selected.
Install the updated `ElectricalCommands.CleanCADCommands` bundle first and select
AutoCAD Core Console in settings. The existing desktop commands remain available.

The confirmation screen lists DWGs directly in `Electrical`, titleblock candidates
under `XREF` or `Xrefs`, and standard sheet sizes found in recent PDFs under `PDF`
and `Electrical/Checkset`. Candidates actually referenced in paper space are marked
and ranked first. Confirm the correct XREF, drawing files, and dimensions. PDF
dimensions are inches; the editable dimensions are CAD units. Mixed PDF page sizes
are offered separately, preserving page orientation. No usable PDF requires manual
dimensions; cleanup never guesses a size from drawing extents.

The titleblock source boundary is `(0,0)` to `(width,height)` in Model Space.
The same rectangle is transformed by each titleblock insertion for paper-space
cleanup. Entity bounding-box intersection is conservative: crossing entities are
retained whole, and a bounding box may intersect even if the entity itself does not.

## Processing and output

1. Inspect the selected DWGs and recursively resolve their DWG dependencies.
   A missing path can resolve to a unique filename under the project's XREF tree;
   missing or ambiguous dependencies stop processing.
2. Copy the dependency graph to a unique local temporary directory. Preserve
   project-relative structure and place outside-project dependencies in unique
   `Dependencies` directories. Rewrite references in these copies only.
3. Stage referenced PDFs/images and rewrite their paths. Plot originals, remove
   titleblock stamps/signatures and plot the removal-only reference. Import supported
   PDF pages as native CAD blocks and raster pixels as colored solids. Save and
   reopen each converted DWG before cleaning the titleblock.
4. Replace the staged titleblock with its validated result. Clean each sheet using
   the explicitly confirmed XREF identity and synchronous `CLEANCAD2` stages.
5. Check for empty drawings, remaining external DWG references, external media,
   and changes in entity counts after reopening. Check source hashes before delivery.
6. Deliver all results together to
   `Project/Cleaned CAD/YYYY-MM-DD_HHMMSS_<unique>/`, preserving `Electrical` and
   XREF paths, with `cleanup-report.json`. The report records confirmed dimensions,
   PDF provenance, validation results, and source hashes.

Before media conversion and titleblock pruning, the staged sheets are plotted as
the original set. Named stamp/signature blocks, XREFs, image files and layers are
then removed from the staged titleblock only. Logos are not removal targets. The
same sheets are plotted again to form a reference containing only those intentional
removals. Sheet-level signatures outside the titleblock are not removal targets.
Removed handles, names and layers are recorded in `titleblockMarkRemoval`.
Mark removal walks layout contents and retained local block insertions. Named
stamp/signature insertions are removed without editing their block definitions,
which can contain protected proxy entities. Unused definitions are left for the
later purge/proxy stage. A protected mark in retained content still stops cleanup
with its handle, layer and containing block identified.
Anonymous/exploded marks without identifying names/layers require visual review.

After cleanup, every original DWG/layout is plotted again. Layout identity and
page sizes must match; missing/failed plots stop the job. All three sets use
DWG To PDF.pc3, full bleed media matching the confirmed dimensions (30 x 42 ARCH
E1 for a 42 x 30 sheet), landscape for wider sheets, Layout at 1:1 inches and zero
offset. Plot styles use `510-monochrome.ctb`; a missing CTB stops the job rather
than substituting a different profile. Lineweights and paperspace-last are on;
transparency, hidden paperspace objects, scaled lineweights and image/PDF frames
are off. Shaded plot quality is Normal. Only the printed sheet is compared, so
monochrome plotting does not detect differences that affect only CAD colors.

Headless model cleanup includes floating viewports on every layout, even when
AutoCAD reports them as off on an inactive tab. The overall paperspace viewport
is identified by its layout ID, not its transient viewport number. Unmeasurable
viewport regions stop pruning before model geometry can be deleted.
Each dated output contains a `Review` directory with:

- `Original Set.pdf`: staged originals before mark removal or cleanup.
- `Reference - stamps removed.pdf`: only the intended titleblock removals applied.
- `Cleaned Set.pdf`: the final DWGs plotted after reopening.
- `Comparison.pdf`: cleaned pages with unexpected pixel differences highlighted red.
- `comparison.json`: per-sheet original-to-cleaned, intentional-removal and
  unexpected-difference pixel counts.

Pixels are compared at 144 DPI with a 24/255 RGB-channel tolerance, without
excluding stamp regions or globally aligning pages. Any unexpected differing pixel
produces **Review required**, an activity warning and a `_REVIEW_REQUIRED` output
folder suffix. Outputs are available for review but are not reported as matching.
No differences means only a match within the stated resolution/tolerance, not a
guarantee of CAD or engineering equivalence. Native PDF import, fonts and lineweight
changes may be visible and require review. No automatic approval or distribution
of review-required files occurs.

Original drawings are never saved. A failure retains local working files and logs,
reports their location, and does not deliver a partial successful batch. A failure
during the final copy can leave a `.incomplete-*` directory in `Cleaned CAD`.
The tool allows one cleanup batch at a time per app process. Each worker has a
five-minute timeout. Cancellation during processing is not implemented in this version.

The picker recommends a titleblock only when exactly one paper-space reference
has a titleblock filename token such as `TB`, `TBLK` or `titleblock`. Otherwise an
explicit selection is required. A paper-space reference alone is not evidence of
a titleblock: site backgrounds and stamps can also appear there. Before scanning
the dependency graph or converting media, `validate-titleblock` checks local
Model Space geometry (including transformed local blocks) against the confirmed
origin/size. This conservative check rejects a wrong, empty boundary early; it
does not replace the later cleanup and validation.

## Current limits

- Wipeout masks are supported; they are not treated as external image attachments.
  Validation records their count and checks it again after reopening the output.
- PDF underlays and supported raster images are converted automatically. PDF
  attachments must be directly in a layout with no custom clip or display adjustment.
  PDFs with annotations, form widgets, optional layers or passwords are refused
  to avoid losing visible content. DGN/DWF and linked OLE remain unsupported.
- The titleblock must contain measurable local geometry. Local blocks that cannot
  be exploded stop processing. Its DWG XREFs are intentionally detached.
- Each sheet must have a uniquely identified titleblock definition in paper space
  and usable viewports when Model Space is nonempty. Empty Model Space is allowed. Multiple titleblock insertions on
  one layout currently stop automatic paper-space cleanup.
- Reopen, count, and reference checks are structural validation, not a rendered
  visual comparison or a guarantee about embedded OLE display/printing.
- There is no full-AutoCAD fallback: unsupported drawings are reported explicitly.

## Batch contract

`ACIES_CLEAN_JOB` is a process-local environment variable containing the absolute
path of a UTF-8 JSON request. Run `ACIESCLEANJOB` after `NETLOAD`. Requests contain
`Operation` and `ResultPath`, plus operation-specific fields:

| Operation | Fields | Purpose |
| --- | --- | --- |
| `scan` | `Files`, `Catalog` | Read DWG graph, XREF candidates, structured `pdfs` and `images`, unsupported `media` |
| `prepare` | `Copies`, `References`, `Pdfs`, `PdfCopies`, `Images`, `ImageCopies` | Rewrite staged DWG and asset paths after checking handles/pages/paths |
| `embed-media` | `Output` (new file only) | Convert local PDF and raster attachments; external DWG refs allowed at this stage |
| `verify-media` | none | Check local entity/solid counts and absence of external media |
| `remove-titleblock-marks` | `Output` (new file) | Remove identifiable stamps/signatures from the active staged titleblock and return an audit list |
| `plot-review` | `Output` (new directory), `Width`, `Height`, optional `Layouts` | Plot nonempty paper layouts to one PDF each; explicit layout lists must match |
| `titleblock` | `Width`, `Height`, `Output` | Fixed-origin titleblock cleanup |
| `sheet` | `Titleblock`, `Width`, `Height`, `Output` | Confirmed-titleblock sheet cleanup |
| `verify` | none | Inspect active saved output |
| `embed-prototype` | `Output` (new file only) | Experimental raster-to-native-solids conversion, separate from cleanup |

`CLEANTBLK2` is an entry point for a `titleblock` request using this same contract.
Each worker writes `{ "success": true, "details": ... }` or
`{ "success": false, "error": ... }`. The app requires both a successful process
exit and a successful result; a log marker alone cannot authorize delivery.

Run unit tests with `.venv/Scripts/python.exe -m unittest tests.test_clean_drawings`.
The optional real AutoCAD test `tests.test_clean_drawings_core` requires
`ACIES_TEST_CORE` and `ACIES_TEST_CLEAN_DLL` pointing to the matching installed
Core Console and built plugin DLL. It creates disposable synthetic DWGs and
checks fixed-origin pruning, XREF binding, reopen results, and original preservation.

## Self-contained image geometry

`embed-prototype` replaces ordinary attached raster images with blocks containing
true-color `SOLID` entities. Recipients need neither the original image files nor
the ACIES plugin. Clean Drawings now uses the same encoder through `embed-media`.
The explicit `embed-prototype` operation remains available for isolated tests.
PDFs use AutoCAD's native `-PDFIMPORT`, not rasterization. DGN/DWF and linked OLE
are not converted. Native text still relies on the recipient's installed fonts.

The prototype decodes source pixels without downsampling or color quantization,
merges equal horizontal runs and matching runs on adjacent rows, and maps them
through the image's original origin and width/height vectors. It preserves the
owner block, layer, entity properties and position in draw order. Unreferenced
raster image definitions are removed; wipeouts are excluded from conversion.

Supported inputs are non-bitonal images parallel to their owner XY plane,
with default brightness/contrast, no fade, unlocked layers
and no partial clipping. AutoCAD's default whole-image clip is accepted. FILLMODE
must be 1. The source path must exist exactly as stored (relative to the input DWG
when applicable); source dimensions must match the attachment. Limits are two
million pixels per image and 50,000 generated solids per drawing. Binary alpha is
supported: transparent pixels are omitted when image transparency is enabled;
otherwise their RGB values are retained. Partial alpha is refused. All images are
validated before mutation. A rejection produces no output DWG. The output path
must not already exist. The pipeline processes staged copies and hashes original
PDF/image files along with original DWGs before delivery.

Invoke using the existing worker from the ProjectManagement Python environment:

```python
from pathlib import Path
from clean_drawings import run_worker

result = run_worker(core_console, plugin_dll, input_dwg,
                    {'Operation': 'embed-prototype', 'Output': str(output_dwg)},
                    Path(local_job_directory))
assert run_worker(core_console, plugin_dll, output_dwg,
                  {'Operation': 'verify'}, Path(local_job_directory)) == result['validation']
```

The result includes image/solid counts under `embedding` and structural checks
under `validation`. Solids follow CAD fill, viewport, and plot-style behavior;
they are not embedded bitmap/OLE objects. Photographs and anti-aliased logos can
generate many entities. PDF import may change text representation and lineweight
rendering. Structural checks do not replace visual QA.

Run `tests.test_native_image_geometry_core` with `ACIES_TEST_CORE` and
`ACIES_TEST_CLEAN_DLL`. It tests rotated pixel geometry after deleting the PNG,
reopens with built-in AutoLISP without NETLOAD, checks native colors/coordinates,
and rejects alpha, partial clipping and excessive geometry. Set
`ACIES_NATIVE_PLOT=1` to plot the source-free output to PDF and verify its vector
fill colors. `ACIES_NATIVE_ARTIFACTS` optionally retains artifacts in a new directory.

`tests.test_headless_media_core` checks a rotated second-page PDF attachment,
source-free reopening/plotting and overwrite rejection. Build the test-only
`ElectricalCommands/tests/HeadlessEmbeddingProbe` project first; Core Console
PDFATTACH cannot create this fixture reliably. A complete local-copy run of the
San Mateo energy drawing (18 PDF pages plus signature images) also passed media
conversion, titleblock cleanup, sheet cleanup and reopen validation.
