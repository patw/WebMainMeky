"""The validation gate: a cheap deterministic check on the extracted markdown.

This is what closes the self-improving loop. Without it, failures are invisible,
the authoring path never fires, and the service quietly returns garbage forever.
"""
from __future__ import annotations

import re

from . import config

NAV_WORDS = re.compile(
    r'\b(navigation|sign in|sign up|log in|login|register|subscribe|newsletter|'
    r'cookie policy|privacy policy|terms of use|terms and conditions|all rights '
    r'reserved|copyright|follow us|share this|search the site|search site|'
    r'sitemap|add to cart|shopping cart|create account|forgot password|'
    r'leave a comment|post a comment|related articles|read more|load more)\b', re.I)

MD_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')
SENT_SPLIT = re.compile(r'(?<=[.!?\u3002\uff01\uff1f\n])\s+')


def _sentences(md: str) -> list[str]:
    parts = [p.strip() for p in SENT_SPLIT.split(md)]
    return [p for p in parts if len(p) >= 12]


def _link_ratio(md: str) -> float:
    total = len(md)
    if not total:
        return 1.0
    linked = sum(len(m.group(1)) for m in MD_LINK.finditer(md))
    return linked / total


def _nav_ratio(md: str) -> float:
    lines = [l for l in md.split('\n') if l.strip()]
    if not lines:
        return 1.0
    nav_lines = sum(1 for l in lines if NAV_WORDS.search(l) and len(l) < 90)
    return nav_lines / len(lines)


def _script_ratio(md: str) -> float:
    letters = re.findall(r'[^\W\d_]', md, flags=re.U)
    if not letters:
        return 0.0
    from collections import Counter
    scripts = Counter()
    for ch in letters:
        o = ord(ch)
        if o < 0x0300:
            scripts['latin'] += 1
        elif 0x4e00 <= o <= 0x9fff:
            scripts['cjk'] += 1
        elif 0x0400 <= o <= 0x04ff:
            scripts['cyrillic'] += 1
        elif 0x3040 <= o <= 0x30ff:
            scripts['kana'] += 1
        elif 0xac00 <= o <= 0xd7af:
            scripts['hangul'] += 1
        else:
            scripts['other'] += 1
    top = scripts.most_common(1)[0][1]
    return top / len(letters)


def validate(md: str, min_chars: int = None, min_sentences: int = None,
             max_link_density: float = None) -> dict:
    min_chars = config.MIN_CHARS if min_chars is None else min_chars
    min_sentences = config.MIN_SENTENCES if min_sentences is None else min_sentences
    max_link_density = config.MAX_LINK_DENSITY if max_link_density is None else max_link_density

    md = md or ''
    sents = _sentences(md)
    chars = len(md.strip())
    link_ratio = _link_ratio(md)
    nav_ratio = _nav_ratio(md)
    script = _script_ratio(md)
    mean_sent = (sum(len(s) for s in sents) / len(sents)) if sents else 0.0
    paragraphs = len([b for b in md.split('\n\n') if b.strip()])

    reasons = []
    if chars < min_chars:
        reasons.append(f'too_short:{chars}<{min_chars}')
    if len(sents) < min_sentences:
        reasons.append(f'too_few_sentences:{len(sents)}<{min_sentences}')
    if mean_sent < 30:
        reasons.append(f'sentences_too_short:{mean_sent:.0f}')
    if link_ratio > max_link_density:
        reasons.append(f'link_density:{link_ratio:.2f}>{max_link_density}')
    if nav_ratio > 0.35:
        reasons.append(f'nav_words:{nav_ratio:.2f}')
    if script < 0.60:
        reasons.append(f'script_mix:{script:.2f}')

    return {
        'ok': not reasons,
        'reasons': reasons,
        'chars': chars,
        'sentences': len(sents),
        'mean_sentence_len': round(mean_sent, 1),
        'paragraphs': paragraphs,
        'link_ratio': round(link_ratio, 3),
        'nav_ratio': round(nav_ratio, 3),
        'script_ratio': round(script, 3),
    }
