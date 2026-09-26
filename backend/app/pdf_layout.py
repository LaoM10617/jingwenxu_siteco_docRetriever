"""Page-local geometry; no product names or document-specific crop coordinates."""
from dataclasses import dataclass
from statistics import median
import re

from pdfplumber.utils import extract_text


@dataclass(frozen=True)
class SourceSpan:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class Region:
    header: tuple[SourceSpan, ...]
    units: tuple[SourceSpan, ...]
    kind: str


def bounds(chars):
    return (min(c['x0'] for c in chars), min(c['top'] for c in chars),
            max(c['x1'] for c in chars), max(c['bottom'] for c in chars))


def span(chars):
    return SourceSpan(extract_text(chars, x_tolerance=2, y_tolerance=3).strip(), bounds(chars))


def _inside(c, box):
    x, y = (c['x0'] + c['x1']) / 2, (c['top'] + c['bottom']) / 2
    return box[0] - 1 <= x <= box[2] + 1 and box[1] <= y <= box[3]


def _bold(chars):
    return sum('bold' in c.get('fontname', '').lower() for c in chars) / len(chars) > .8


def _rules(page, size):
    # Join touching cell borders, then group repeated full-width horizontal rules.
    rows = []
    for edge in sorted((e for e in page.edges if e['orientation'] == 'h'), key=lambda e: e['top']):
        if not rows or abs(rows[-1][0] - edge['top']) > 1:
            rows.append((edge['top'], []))
        rows[-1][1].append((edge['x0'], edge['x1']))
    merged = []
    for y, intervals in rows:
        joined = []
        for left, right in sorted(intervals):
            if joined and left <= joined[-1][1] + 2:
                joined[-1] = (joined[-1][0], max(joined[-1][1], right))
            else:
                joined.append((left, right))
        merged.extend((left, right, y) for left, right in joined if right - left > 6 * size)
    runs = []
    for left, right, y in sorted(merged, key=lambda r: r[2]):
        run = next((r for r in reversed(runs) if abs(r[0] - left) < 2 and abs(r[1] - right) < 2
                    and y - r[2][-1] <= 5 * size), None)
        if run is None:
            runs.append((left, right, [y]))
        else:
            run[2].append(y)
    return [r for r in runs if len(r[2]) >= 3]


def _lines(chars):
    rows = []
    for c in sorted(chars, key=lambda c: (c['top'], c['x0'])):
        if not rows or abs(rows[-1][0]['top'] - c['top']) > 3:
            rows.append([])
        rows[-1].append(c)
    return rows


def _blocks(chars, size, depth=0):
    # Whitespace cuts operate on whole words, so ordinary word spacing cannot split a column.
    from pdfplumber.utils import extract_words
    words = extract_words(chars)
    if depth >= 12 or len(words) < 2:
        return [chars]
    for axis, end, threshold in [('top', 'bottom', 5 * size), ('x0', 'x1', 2.5 * size)]:
        extent, gaps = None, []
        for word in sorted(words, key=lambda w: w[axis]):
            if extent is not None and word[axis] - extent > threshold:
                gaps.append((word[axis] - extent, (word[axis] + extent) / 2))
            extent = max(extent or word[end], word[end])
        if gaps:
            cut = max(gaps)[1]
            a = [c for c in chars if (c[axis] + c[end]) / 2 < cut]
            b = [c for c in chars if (c[axis] + c[end]) / 2 >= cut]
            return _blocks(a, size, depth + 1) + _blocks(b, size, depth + 1)
    return [chars]


def _paragraphs(chars):
    units, current = [], []
    left = min(c['x0'] for c in chars)
    for row in _lines(chars):
        text = span(row).text
        # Keep indented subclauses with their parent and all continuation lines.
        starts = re.match(r'^(?:\d+[.)]|[•●])\s', text)
        if current and starts and min(c['x0'] for c in row) <= left + 3:
            units.append(span(current))
            current = []
        current.extend(row)
    if current:
        units.append(span(current))
    return tuple(s for s in units if s.text)


def group_page(page):
    chars = list(page.chars)
    if not chars:
        return (), False
    size = median(c['size'] for c in chars)
    regions, used = [], set()
    for left, right, ys in _rules(page, size):
        box = (left, ys[0] - 5 * size, right, ys[-1])
        selected = [c for c in chars if id(c) not in used and c.get('upright', True) and _inside(c, box)]
        units, header = [], []
        for top, bottom in zip([box[1]] + ys, ys):
            row = [c for c in selected if top <= (c['top'] + c['bottom']) / 2 < bottom]
            if row:
                if not units and (top == box[1] or _bold(row)):
                    header.append(span(row))
                else:
                    units.append(span(row))
        if not units:
            continue
        regions.append(Region(tuple(header), tuple(units), 'table'))
        used.update(id(c) for c in selected)
    remaining = [c for c in chars if id(c) not in used]
    uncertain = any(not c.get('upright', True) for c in remaining)
    # Rotated captions remain isolated; never attach them to a nearby product table.
    for upright in (True, False):
        subset = [c for c in remaining if c.get('upright', True) == upright]
        if not subset:
            continue
        for block in _blocks(subset, size):
            rows = _lines(block)
            ambiguous = any(any(b['x0'] - a['x1'] > 4 * size for a, b in zip(ordered, ordered[1:]))
                            for ordered in (sorted(row, key=lambda c: c['x0']) for row in rows))
            if ambiguous or not upright:
                uncertain = True
                native = span(block)
                if native.text:
                    regions.append(Region((), (native,), 'fallback'))
                continue
            header, body = [], []
            for row in rows:
                if _bold(row):
                    if body:
                        regions.append(Region(tuple(header), _paragraphs(body), 'text'))
                        header, body = [], []
                    header.append(span(row))
                else:
                    body.extend(row)
            if header or body:
                regions.append(Region(tuple(header), _paragraphs(body) if body else (), 'text'))
    regions = [r for r in regions if r.header or r.units]
    # A single prominent heading above all tables is page context, not a guessed model.
    titles = [row for row in _lines(chars) if min(c['size'] for c in row) >= 1.8 * size
              and any(c['text'].isalpha() for c in row)]
    tables = [r for r in regions if r.kind == 'table']
    if len(titles) == 1 and tables:
        title = span(titles[0])
        if title.bbox[3] < min((r.header + r.units)[0].bbox[1] for r in tables):
            regions = [Region((title,) + r.header, r.units, r.kind) if r.kind == 'table' else r for r in regions]
    return tuple(sorted(regions, key=lambda r: (r.header + r.units)[0].bbox[1::-1])), uncertain
