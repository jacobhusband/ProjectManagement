"""Three-way plotted comparison: originals, approved mark removal, cleaned output."""
import io
import json
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageChops


def _render(page, dpi):
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)


def _difference(left, right, tolerance):
    channels = ImageChops.difference(left, right).split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    mask = maximum.point(lambda value: 255 if value > tolerance else 0)
    return mask, mask.histogram()[255]


def compare_sets(originals, reference, cleaned, output, notify=lambda message: None, dpi=144, tolerance=24):
    """Pair by DWG/layout identity, never by coincidental PDF page order.

    No area is masked out. Expected removals have their own independently plotted
    reference. Any other pixel difference above the color tolerance needs review.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    def indexed(records):
        values = {(r['drawing'], r['layout']): r for r in records}
        if len(values) != len(records):
            raise RuntimeError('Duplicate drawing/layout in PDF comparison.')
        return values
    groups = [indexed(records) for records in (originals, reference, cleaned)]
    if not groups[0] or any(set(group) != set(groups[0]) for group in groups[1:]):
        raise RuntimeError('Original/reference/cleaned PDF layout lists do not match.')
    names = ('Original Set.pdf', 'Reference - stamps removed.pdf', 'Cleaned Set.pdf')
    merged = [fitz.open() for _ in names]
    comparison = fitz.open()
    records = []
    try:
        for index, key in enumerate(groups[0], 1):
            notify(f'Comparing plotted sheet {index} of {len(groups[0])}: {key[0]} / {key[1]}')
            documents = [fitz.open(group[key]['file']) for group in groups]
            try:
                if any(len(doc) != 1 for doc in documents):
                    raise RuntimeError('Each layout plot must contain exactly one PDF page.')
                # AutoCAD encodes landscape via /Rotate. Normalize the page contents
                # before embedding them, otherwise vector pages and pixel overlays turn differently.
                for document in documents:
                    document[0].remove_rotation()
                sizes = [(round(doc[0].rect.width, 3), round(doc[0].rect.height, 3)) for doc in documents]
                if len(set(sizes)) != 1:
                    raise RuntimeError(f'PDF page size changed: {key}')
                if sizes[0][0] * sizes[0][1] * (dpi / 72) ** 2 > 40000000:
                    raise RuntimeError('Review page exceeds the 40-million-pixel comparison limit.')
                for target, source in zip(merged, documents):
                    target.insert_pdf(source)
                images = [_render(doc[0], dpi) for doc in documents]
                if len({image.size for image in images}) != 1:
                    raise RuntimeError(f'PDF raster dimensions changed: {key}')
                if ImageChops.invert(images[0]).getbbox() is None:
                    raise RuntimeError(f'Original layout plotted blank; refusing to certify a blank comparison: {key}')
                mask, changed = _difference(images[1], images[2], tolerance)
                _, total_changed = _difference(images[0], images[2], tolerance)
                _, intentional = _difference(images[0], images[1], tolerance)
                pixels = images[0].width * images[0].height
                records.append({'drawing': key[0], 'layout': key[1], 'page': index,
                                'status': 'review_required' if changed else 'match_within_tolerance',
                                'unexpectedPixels': changed, 'unexpectedPercent': round(100 * changed / pixels, 6),
                                'originalToCleanedPixels': total_changed, 'intentionalRemovalPixels': intentional})
                width, height = sizes[0]
                page = comparison.new_page(width=width, height=height + 40)
                page.insert_text((12, 15), f'{index}: {key[0]} / {key[1]}', fontsize=9)
                page.insert_text((12, 29), f'{records[-1]["status"]}: {changed:,} unexpected pixels. Red = changes beyond stamp/signature and revision cloud/delta removal.', fontsize=9)
                rectangle = fitz.Rect(0, 40, width, height + 40)
                page.show_pdf_page(rectangle, documents[2], 0)
                if changed:
                    overlay = Image.new('RGBA', mask.size, (255, 0, 0, 0))
                    overlay.putalpha(mask.point(lambda value: 150 if value else 0))
                    stream = io.BytesIO()
                    overlay.save(stream, format='PNG')
                    page.insert_image(rectangle, stream=stream.getvalue())
            finally:
                for document in documents:
                    document.close()
        for name, document in zip(names, merged):
            document.set_toc([[1, f'{key[0]} / {key[1]}', i] for i, key in enumerate(groups[0], 1)])
            document.save(output / name, garbage=4, deflate=True)
        comparison.save(output / 'Comparison.pdf', garbage=4, deflate=True)
        report = {'status': 'review_required' if any(r['unexpectedPixels'] for r in records) else 'match_within_tolerance',
                  'dpi': dpi, 'channelTolerance': tolerance, 'pages': records,
                  'method': 'Original-to-cleaned differences and reference-to-cleaned differences. Reference has only named titleblock stamps/signatures removed and revision cloud/delta layers frozen, as sheet cleanup does. No excluded regions.',
                  'limitation': 'A rendered comparison at finite resolution/tolerance is not proof of CAD or engineering equivalence. Review highlighted differences; fonts and native PDF import can affect rendering.'}
        (output / 'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report
    finally:
        for document in merged:
            document.close()
        comparison.close()
