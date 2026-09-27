"""Bounded local page rendering with source coordinates, never model positions."""
from base64 import b64encode
from io import BytesIO
from math import isfinite
from threading import Lock

import pdfplumber

from app.documents import DocumentError

# PDFium is not thread-safe. All rendering enters through this lock.
_render_lock = Lock()
MAX_EDGE = 1600


def render_pdf(path, source):
    number = source['locator'].get('page_number')
    if type(number) is not int or number < 1:
        raise DocumentError('preview_unavailable', 'The source has no valid original page.', 422)
    try:
        with _render_lock, pdfplumber.open(path) as pdf:
            if number > len(pdf.pages):
                raise ValueError('Missing page')
            page = pdf.pages[number - 1]
            sizes = [page.width, page.height, page.cropbox[2] - page.cropbox[0],
                     page.cropbox[3] - page.cropbox[1]]
            if not all(isfinite(v) and 0 < v <= 14400 for v in sizes):
                raise ValueError('Unsupported page size')
            raster = page.to_image(resolution=min(144, MAX_EDGE * 72 / max(sizes)), antialias=True)
            image = raster.original
            if max(image.size) > MAX_EDGE:
                image.thumbnail((MAX_EDGE, MAX_EDGE))
            regions, notice = [], None
            spans = [('evidence', s) for s in source.get('source_spans', [])]
            spans += [('context', s) for s in source.get('context', [])]
            # pdfplumber's rotated CropBox normalization does not account for the
            # MediaBox origin. PDFium renders the crop relative to the media bounds.
            mx0, my0, mx1, my1 = page.page_obj.mediabox
            cx0, cy0, cx1, cy1 = page.page_obj.cropbox
            offsets = {0: (cx0-mx0, my1-cy1), 90: (cy0-my0, cx0-mx0),
                       180: (mx1-cx1, cy0-my0), 270: (my1-cy1, mx1-cx1)}
            dx, dy = offsets.get(page.rotation, (0, 0))
            left, top = page.mediabox[0] + dx, page.mediabox[1] + dy
            width, height = cx1-cx0, cy1-cy0
            if page.rotation in (90, 270):
                width, height = height, width
            right, bottom = left+width, top+height
            # Reject questionable geometry as a whole instead of showing partial precision.
            if (not spans or page.rotation not in (0, 90, 180, 270)
                    or not (mx0 <= cx0 < cx1 <= mx1 and my0 <= cy0 < cy1 <= my1)):
                notice = 'Reliable source coordinates are unavailable; showing the original page only.'
            else:
                for role, span in spans:
                    box = span.get('bbox')
                    if (not isinstance(box, (list, tuple)) or len(box) != 4
                            or not all(isinstance(v, (int, float)) and isfinite(v) for v in box)):
                        notice = 'Reliable source coordinates are unavailable; showing the original page only.'
                        break
                    x0, y0, x1, y1 = box
                    if not (left <= x0 < x1 <= right and top <= y0 < y1 <= bottom):
                        notice = 'Source regions extend outside the visible page; showing the original page only.'
                        break
                    regions.append({'role': role, 'box': [(x0-left)/width, (y0-top)/height,
                                                        (x1-x0)/width, (y1-y0)/height]})
            if notice:
                regions = []
            stream = BytesIO()
            image.save(stream, format='PNG')
            return {'kind': 'pdf', 'page_number': number, 'width': image.width, 'height': image.height,
                    'image': 'data:image/png;base64,' + b64encode(stream.getvalue()).decode('ascii'),
                    'regions': regions, 'notice': notice}
    except DocumentError:
        raise
    except Exception:
        # Do not expose parser diagnostics, original paths or source contents in errors.
        raise DocumentError('preview_unavailable', 'Cannot render the original page. The source text remains available.', 503) from None
