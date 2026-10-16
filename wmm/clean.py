"""Line-level boilerplate filtering, applied at serialization time.

Rationale: on forums, listings and Q&A pages the same chrome strings repeat inside
the content subtree (per-post toolbars, "posted by", tag lists, pagination). Node
selection cannot remove them because they live *inside* the content container, so
they are removed by shape at render time.

Everything here is a deterministic string rule. Nothing is learned.
"""
from __future__ import annotations

import re
from collections import Counter

NAV_LINE = re.compile(
    r'^\s*(sign ?in|sign ?up|log ?in|login|register|subscribe|newsletter|search|'
    r'share|tweet|facebook|twitter|pinterest|email this|print|reply|quote|quote ?post|'
    r'edit|delete|report|permalink|permanent link|trackback|report this|'
    r'add ?to ?cart|wishlist|compare|next|previous|page ?\d+|\d+\s*$)\b[^\n]{0,40}$',
    re.I)
NAV_WORDS = re.compile(
    r'\b(navigation|sign in|sign up|log in|login|register|subscribe|newsletter|'
    r'cookie policy|privacy policy|terms of use|terms and conditions|all rights '
    r'reserved|copyright|follow us|share this|search the site|sitemap|add to cart|'
    r'shopping cart|create account|forgot password|leave a comment|post a comment|'
    r'related articles|read more|load more|posted by|tags:|categories:|filed under|'
    r'reply|quote|permalink|page ?\d+|of ?\d+|jump to|top of page|bottom of page)\b',
    re.I)
SEPARATOR_ONLY = re.compile(r'^[\s|·•·\-\*/\\~•]+$')
ALL_CAPS_SHORT = re.compile(r'^[A-Z0-9 &\.\',:/\(\)\-]{3,40}$')
CODEISH = re.compile(r'^\s*(```|    |\|\s|>)')


def _norm(line: str) -> str:
    return re.sub(r'\s+', ' ', line).strip().lower()


def boilerplate_reasons(line: str, repeats: int = 1) -> list[str]:
    raw = line.strip()
    out = []
    if not raw:
        return out
    if SEPARATOR_ONLY.match(raw):
        out.append('separator')
    if NAV_LINE.match(raw):
        out.append('nav_line')
    if len(raw) < 70 and NAV_WORDS.search(raw) and not raw.endswith(('.', '!', '?')):
        out.append('nav_words')
    if ALL_CAPS_SHORT.match(raw) and len(raw.split()) <= 6 and not raw.endswith(('.', '!')):
        out.append('caps_menu')
    if repeats >= 3 and len(raw) < 60 and not raw.endswith(('.', '!', '?')):
        out.append(f'repeated:{repeats}')
    return out


def is_boilerplate(line: str, repeats: int = 1) -> bool:
    return bool(boilerplate_reasons(line, repeats))


def filter_lines(lines: list[str]) -> list[str]:
    """Drop boilerplate lines from a multi-line block (lists, tables, code kept)."""
    return filter_lines_with_counts(lines, line_counts([('\n'.join(lines))]))


def line_counts(blocks: list[str]) -> Counter:
    """Normalized line frequencies across the whole rendered document."""
    c = Counter()
    for b in blocks:
        if b.startswith('```'):
            continue
        for line in b.split('\n'):
            n = _norm(line)
            if n:
                c[n] += 1
    return c


def filter_lines_with_counts(lines: list[str], counts: Counter) -> list[str]:
    kept = []
    for l in lines:
        if CODEISH.match(l):
            kept.append(l)
            continue
        if is_boilerplate(l, counts.get(_norm(l), 1)):
            continue
        kept.append(l)
    return kept


def filter_block(block: str) -> str:
    return filter_block_with_counts(block, line_counts([block]))


def filter_block_with_counts(block: str, counts: Counter) -> str:
    """Filter a rendered block. Code blocks and table grids are left intact -
    a grid's separator row is punctuation, not boilerplate."""
    if not block.strip():
        return block
    if block.startswith('```') or block.lstrip().startswith('|'):
        return block
    lines = block.split('\n')
    if len(lines) == 1:
        return '' if is_boilerplate(lines[0], counts.get(_norm(lines[0]), 1)) else block
    kept = filter_lines_with_counts(lines, counts)
    if not kept:
        return ''
    # a table that lost its header row is not a table any more
    if block.lstrip().startswith('|') and len(kept) < 2:
        return ''
    return '\n'.join(kept)
