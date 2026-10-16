"""DOM -> Markdown serializer with pluggable convention profiles.

The document model is built first (a list of typed blocks), then rendered. Format
conventions live in the profile, not scattered through the walker - so the same
extraction can be emitted as clean GFM for downstream use, or in the shape a
specific benchmark's ground truth happens to take.
"""
from __future__ import annotations

import re

from . import clean, mathfmt, trim
from .dom import HEADINGS, SKIP_TAGS, hidden

PROFILES = ('canonical', 'gt')


class Profile:
    def __init__(self, name: str):
        if name not in PROFILES:
            raise ValueError(f'unknown profile {name}')
        self.name = name
        self.keep_links = (name == 'canonical')
        self.keep_images = False
        self.escape_dollars = (name == 'gt')
        self.fence_code = True
        self.pipe_tables = True


# --------------------------------------------------------------------- marks
def mark_all(root):
    for el in root.iter():
        if isinstance(el.tag, str):
            el.set('__keep', '1')
    return root


def is_marked(el) -> bool:
    return el.get('__keep') == '1'


# ----------------------------------------------------------------- inline text
def _inline(el, prof: Profile) -> str:
    parts = [el.text or '']
    for child in el.iterchildren():
        if not isinstance(getattr(child, 'tag', None), str):
            parts.append(str(child))
            continue
        tag = child.tag
        tail = child.tail or ''

        if tag in SKIP_TAGS:
            parts.append(tail)
        elif tag == 'br':
            parts.append('\n')
        elif tag == 'img':
            if prof.keep_images:
                alt = (child.get('alt') or '').strip()
                src = (child.get('src') or '').strip()
                parts.append(f'![{alt}]({src})' if src else '')
            parts.append(tail)
        elif tag == 'math':
            parts.append(_mathml_tex(child) + tail)
        elif child.get('data-latex') or child.get('alttext'):
            tex = (child.get('data-latex') or child.get('alttext') or '').strip()
            parts.append(f'$${tex}$$' + tail)
        elif tag in ('code', 'kbd', 'samp', 'var', 'tt'):
            inner = re.sub(r'\s+', ' ', _inline(child, prof)).strip()
            parts.append((f'`{inner}`' if inner else '') + tail)
        elif tag in ('strong', 'b'):
            inner = _inline(child, prof).strip()
            parts.append((f'**{inner}**' if inner else '') + tail)
        elif tag in ('em', 'i'):
            inner = _inline(child, prof).strip()
            parts.append((f'*{inner}*' if inner else '') + tail)
        elif tag == 'a':
            inner = _inline(child, prof)
            href = (child.get('href') or '').strip()
            if prof.keep_links and href and inner.strip():
                parts.append(f'[{inner.strip()}]({href})')
            else:
                parts.append(inner)
            parts.append(tail)
        else:
            parts.append(_inline(child, prof))
            parts.append(tail)
    return ''.join(parts)


def _mathml_tex(el) -> str:
    for ann in el.iter('annotation'):
        if 'tex' in (ann.get('encoding') or ''):
            return f"$${(ann.text or '').strip()}$$"
    alt = el.get('alttext')
    return f"$${alt.strip()}$$" if alt else ''


# ------------------------------------------------------------------- blocks
def _cell_text(cell, prof: Profile) -> str:
    nested = cell.find('.//table')
    if nested is not None:
        # nested tables are flattened to text; the ground truth keeps raw HTML for
        # these, so there is nothing to match structurally
        text = nested.text_content()
        nested.getparent().remove(nested)
        return re.sub(r'\s+', ' ', _inline(cell, prof) + ' ' + text).strip()
    t = _inline(cell, prof)
    t = re.sub(r'\s*\n\s*', ' <br> ', t)
    t = t.replace('|', '\\|')
    return re.sub(r'\s+', ' ', t).strip()


def _table_to_md(tbl, prof: Profile) -> str:
    """Rebuild the table as a rectangular grid: colspan/rowspan expansion,
    header-row detection, direct-child rows only (nested tables flattened)."""
    rows_els = []
    for section in ('thead', 'tbody', 'tfoot'):
        for body in tbl.findall('./' + section):
            rows_els.extend(tr for tr in body.iterchildren()
                            if isinstance(tr.tag, str) and tr.tag == 'tr')
    direct = [c for c in tbl.iterchildren() if isinstance(c.tag, str) and c.tag == 'tr']
    if direct:
        rows_els = direct + rows_els
    if not rows_els:
        rows_els = list(tbl.iter('tr'))
    if not rows_els:
        return ''

    grid: list[list[str]] = []
    header_rows: set[int] = set()
    occupied: dict[tuple[int, int], bool] = {}

    for ri, tr in enumerate(rows_els):
        cells = [c for c in tr.iterchildren()
                 if isinstance(c.tag, str) and c.tag in ('td', 'th')]
        if not cells:
            continue
        row = []
        col = 0
        is_header = any(c.tag == 'th' for c in cells)
        if is_header:
            header_rows.add(ri)
        for c in cells:
            while occupied.get((ri, col)):
                col += 1
            span = _span(c.get('colspan'))
            rowspan = _span(c.get('rowspan'))
            text = _cell_text(c, prof)
            for dc in range(span):
                for dr in range(rowspan):
                    occupied[(ri + dr, col + dc)] = True
                row.append((col + dc, text if dc == 0 else ''))
            col += span
        if row:
            grid.append([t for _, t in sorted(row)])
            grid[-1] = [t for _, t in sorted(row)]

    if not grid:
        return ''
    ncols = max(len(r) for r in grid)
    grid = [r + [''] * (ncols - len(r)) for r in grid]

    header_idx = sorted(header_rows)
    if header_idx:
        head = []
        for r_i in header_idx:
            head.extend(grid[r_i])
        head = head[:ncols] + [''] * max(0, ncols - len(head))
        body = [grid[i] for i in range(len(grid)) if i not in header_rows]
    else:
        head = grid[0]
        body = grid[1:]

    out = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * ncols]
    out += ['| ' + ' | '.join(r) + ' |' for r in body]
    return '\n'.join(out)


def _span(v) -> int:
    try:
        n = int(str(v).strip())
        return max(1, min(n, 50))
    except (TypeError, ValueError):
        return 1


LAYOUT_TABLE_TAGS = ('nav', 'header', 'footer', 'aside', 'form', 'select')


def _is_page_scaffold(tbl) -> bool:
    """A table holding most of the page's text is a layout scaffold (classic forum /
    table-layout pages). The ground truth renders those as prose, not as a grid."""
    root = tbl.getroottree().getroot()
    page = len(root.text_content().strip())
    here = len(tbl.text_content().strip())
    return page > 0 and here / page > 0.70


def table_is_content(tbl) -> bool:
    """Layout tables are chrome: the ground truth drops them, and emitting them
    costs a whole sub-metric. A table counts as content when it carries prose,
    not links - header row, reasonable cell length, low link density."""
    for a in tbl.iterancestors():
        if isinstance(a.tag, str) and a.tag in LAYOUT_TABLE_TAGS:
            return False
        cls = f"{a.get('class', '')} {a.get('id', '')}".lower()
        if any(k in cls for k in ('nav', 'menu', 'calendar', 'breadcrumb', 'cart',
                                  'sidebar', 'ads', 'banner', 'footer', 'header')):
            return False

    rows = list(tbl.iter('tr'))
    if len(rows) < 2:
        return False
    cells = [c for tr in rows for c in tr.iterchildren()
             if isinstance(c.tag, str) and c.tag in ('td', 'th')]
    if len(cells) < 4:
        return False
    has_header = any(c.tag == 'th' for c in cells)

    texts = [c.text_content().strip() for c in cells]
    filled = [t for t in texts if t]
    if not filled:
        return False
    mean_len = sum(len(t) for t in filled) / len(filled)
    total = sum(len(t) for t in texts)
    linked = sum(len(a.text_content().strip()) for a in tbl.iter('a'))
    link_ratio = linked / max(total, 1)

    if has_header and mean_len >= 4 and link_ratio < 0.7:
        return True
    return mean_len >= 8 and link_ratio < 0.4


def _list_to_md(el, prof: Profile, ordered: bool) -> str:
    lines, idx = [], 1
    for li in el.iterchildren('li'):
        body = _inline(li, prof).strip()
        body = re.sub(r'\s*\n\s*', '\n  ', body)
        body = re.sub(r'\n{2,}', '\n  ', body)
        lines.append((f'{idx}. ' if ordered else '- ') + body)
        idx += 1
    return '\n'.join(lines)


def _clean_ws(s: str) -> str:
    s = s.replace('\u00a0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r' ?\n ?', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def _has_block_child(el) -> bool:
    return any(isinstance(c.tag, str) and c.tag in (
        'p', 'div', 'section', 'article', 'main', 'header', 'footer', 'aside',
        'ul', 'ol', 'li', 'table', 'pre', 'blockquote', 'h1', 'h2', 'h3', 'h4',
        'h5', 'h6', 'figure', 'dl', 'center', 'address', 'dd', 'dt', 'body')
        for c in el.iterchildren())


def _walk(el, out: list[str], prof: Profile, filter_mode: bool):
    tag = getattr(el, 'tag', None)
    if not isinstance(tag, str) or tag in SKIP_TAGS or hidden(el):
        return
    if filter_mode and not is_marked(el):
        for c in el.iterchildren():
            if isinstance(c.tag, str):
                _walk(c, out, prof, filter_mode)
        return

    if tag in HEADINGS:
        t = _clean_ws(_inline(el, prof))
        if t:
            out.append('#' * HEADINGS[tag] + ' ' + t)
        return
    if tag == 'pre':
        code = el.text_content().replace('\u00a0', ' ')
        if code.strip():
            out.append('```\n' + code.strip('\n') + '\n```' if prof.fence_code
                       else '\n'.join('    ' + l for l in code.strip('\n').split('\n')))
        return
    if tag == 'table':
        if not table_is_content(el) or _is_page_scaffold(el):
            # layout table: keep its text as prose, do not emit a grid
            for c in el.iterchildren():
                if isinstance(c.tag, str):
                    _walk(c, out, prof, filter_mode)
            return
        md = _table_to_md(el, prof)
        if md:
            out.append(md)
        return
    if tag in ('ul', 'ol'):
        md = _list_to_md(el, prof, tag == 'ol')
        if md.strip():
            out.append(md)
        return
    if tag == 'blockquote':
        sub = []
        for c in el.iterchildren():
            if isinstance(c.tag, str):
                _walk(c, sub, prof, filter_mode)
        if sub:
            out.append('\n'.join('> ' + b for b in sub))
        return
    if tag == 'hr':
        out.append('---')
        return

    if _has_block_child(el):
        for c in el.iterchildren():
            if isinstance(c.tag, str):
                _walk(c, out, prof, filter_mode)
        if el.tail and el.tail.strip():
            t = _clean_ws(el.tail)
            if t:
                out.append(t)
        return

    t = _clean_ws(_inline(el, prof))
    if t:
        out.append(t)
    if el.tail and el.tail.strip():
        t2 = _clean_ws(el.tail)
        if t2:
            out.append(t2)


def render(root, profile: str = 'canonical', filter_mode: bool = True) -> str:
    prof = Profile(profile)
    out: list[str] = []
    _walk(root, out, prof, filter_mode)

    # boilerplate pass: chrome strings that live *inside* the content subtree
    # (per-post toolbars, tag lists, pagination) are removed by line shape
    counts = clean.line_counts(out)
    out = [clean.filter_block_with_counts(b, counts) for b in out]
    out = trim.trim_blocks(out)

    md = '\n\n'.join(b for b in out if b.strip())
    if prof.escape_dollars:
        md = mathfmt.escape_dollars(md)
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md.strip() + '\n'
