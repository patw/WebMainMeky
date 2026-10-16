"""Output trimming.

Measured diagnosis (250 pages, generic tier): precision 0.45 / recall 0.79 on hard
pages, and 65 pages emit more than twice the ground-truth length. The loss is junk in
the output, not missing content - so the lever is trimming, not finding more.

All rules are deterministic string/shape checks on already-rendered blocks.
"""
from __future__ import annotations

import re

from . import config

# headings that end the article: everything after them is commentary, chrome, or
# a recommendation rail
STOP_HEADINGS = re.compile(
    r'^#{1,6}\s*(leave a (reply|comment)|write a comment|add a comment|your comment|'
    r'reply to this comment|respond to|post a comment|comments ?\(|'
    r'related (posts|articles|stories|links|content)|you (may|might) also (like|enjoy)|'
    r'recent posts|latest posts|more posts|recommended (for you|articles)|'
    r'suggested (reads|articles)|read next|up next|continue reading|'
    r'about the author|author bio|about this author|bio|'
    r'share (this|this post|this article)|follow us|follow me|subscribe|newsletter|'
    r'sign up|create (an )?account|sign in|log ?in|'
    r'tags?:|categories?:|filed under|topics?:|archive|archives|'
    r'article (info|metadata)|page information|site map|sitemap|'
    r'popular posts|most read|most popular|sidebar|calendar|'
    r'contact us|contact information|about us|our services|'
    r'advertise|advertisements|sponsored|in association with)\b', re.I)

# a block that is a list of links is a menu, not an article
LINK_LIST_FRACTION = 0.6
MIN_CHARS_BEFORE_STOP = config.MIN_CHARS_BEFORE_STOP


def is_stop_heading(block: str) -> bool:
    return bool(STOP_HEADINGS.match(block.strip()))


def link_fraction(block: str) -> float:
    """Share of a block's visible text that came from link text."""
    md = block
    total = len(re.sub(r'\s+', '', md))
    if not total:
        return 0.0
    linked = sum(len(m.group(1)) for m in re.finditer(r'\[([^\]]*)\]\([^)]*\)', md))
    return linked / total


def is_link_list(block: str) -> bool:
    lines = [l for l in block.split('\n') if l.strip()]
    if len(lines) < 3:
        return False
    bullets = sum(1 for l in lines if re.match(r'^\s*([-*+]|\d+\.)\s', l))
    if bullets < 2:
        return False
    return link_fraction(block) > LINK_LIST_FRACTION


def is_low_value(block: str) -> bool:
    """Short, punctuation-free, sentence-less blocks are menus and labels."""
    b = block.strip()
    if not b:
        return True
    if b.startswith('#') or b.startswith('```') or b.startswith('|'):
        return False
    if len(b) >= 120:
        return False
    if re.search(r'[.!?\u3002\uff01\uff1f]', b):
        return False
    words = len(b.split())
    return words <= 8


def trim_blocks(blocks: list[str]) -> list[str]:
    """Drop junk blocks, and stop at a commentary/recommendation heading once the
    article is already substantial."""
    out = []
    chars = 0
    for b in blocks:
        if not b.strip():
            continue
        if config.TRIM_STOP and is_stop_heading(b) and chars >= MIN_CHARS_BEFORE_STOP:
            break
        if config.TRIM_LINKLIST and is_link_list(b):
            continue
        if config.TRIM_LOWVALUE and is_low_value(b):
            continue
        out.append(b)
        chars += len(b)
    return out
