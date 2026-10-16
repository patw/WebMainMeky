"""Content selection: three tiers, all deterministic.

  tier 1  rule hit      - a promoted layout rule supplies include/exclude XPaths
  tier 2  generic       - prose scoring + link density + landmarks + title alignment
  tier 3  fallback      - densest block, low confidence

Selection marks nodes with a __keep DOM attribute (lxml element proxies are
recreated per traversal, so identity-based sets are unreliable).
"""
from __future__ import annotations

import re

from . import config
from .dom import (CONTENT_KW, attrs_id, hidden, is_chrome, jsonld_types,
                  landmark_score, link_density, link_len, og_title, page_title,
                  parse_html, semantic_tokens, text_len)

CONTENT_TAGS = ('div', 'section', 'article', 'main', 'td')
PROSE_TAGS = ('p', 'li', 'pre', 'blockquote', 'dd', 'dt', 'h1', 'h2', 'h3', 'h4',
              'td', 'th')
# strings that mark a block as chrome when they dominate its own text
BOILER_RE = re.compile(
    r'\b(sign ?in|sign ?up|log ?in|login|register|subscribe|newsletter|search|'
    r'sitemap|cookie policy|privacy policy|terms of use|all rights reserved|'
    r'copyright|follow us|share this|add to cart|shopping cart|create account|'
    r'forgot password|leave a comment|post a comment|related articles|read more|'
    r'load more|posted by|tags:|categories:|filed under|permalink|page ?\d+|'
    r'of ?\d+|top of page|bottom of page|previous|next)\b', re.I)


def clear_marks(root):
    for el in root.iter():
        if isinstance(el.tag, str) and el.get('__keep') is not None:
            del el.attrib['__keep']
    return root


def mark_subtree(el):
    for n in el.iter():
        if isinstance(n.tag, str):
            n.set('__keep', '1')
    for a in el.iterancestors():
        a.set('__keep', '1')


def _eval_xpaths(root, exprs) -> list:
    found = []
    for expr in exprs or []:
        try:
            found.extend(root.xpath(expr))
        except Exception:
            continue
    return [el for el in found if isinstance(getattr(el, 'tag', None), str)]


def apply_rule(root, include_xpaths, exclude_xpaths=()) -> int:
    """Tier 1. Returns the number of nodes matched by the include selectors."""
    hits = []
    for expr in include_xpaths or []:
        try:
            hits.extend(root.xpath(expr))
        except Exception:
            continue
    for el in hits:
        if isinstance(el.tag, str):
            mark_subtree(el)
    for el in _eval_xpaths(root, exclude_xpaths):
        for n in el.iter():
            if isinstance(n.tag, str) and n.get('__keep') == '1':
                del n.attrib['__keep']
    return len(hits)


def prune_unmarked(root):
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        if el.get('__keep') == '1':
            continue
        if el.getparent() is not None:
            el.drop_tree()
    return root


# ------------------------------------------------------------------ tier 2
def _title_tokens(s: str) -> set[str]:
    return {w for w in re.findall(r'[a-zA-Z0-9]{4,}', (s or '').lower())}


def prose_score(el) -> float:
    """Reward long prose and runs of consecutive prose siblings; ignore link text.

    This is the piece the old density score was missing: a forum post body and a
    tag cloud can have similar text length, but only one of them is a run of
    substantial paragraphs.
    """
    total = 0.0
    run = 0
    best_run = 0
    for c in el.iter():
        if not isinstance(c.tag, str) or c.tag not in PROSE_TAGS:
            continue
        if c.tag in ('li', 'td', 'th'):
            # a list/table cell counts only if it is not a pure link
            if link_density(c) > 0.6:
                continue
        n = len(c.text_content().strip())
        if n < config.MIN_PROSE:
            continue
        total += min(n, 500)
        parent = c.getparent()
        if parent is not None and all(
                isinstance(sib.tag, str) and sib.tag in PROSE_TAGS
                for sib in parent.iterchildren() if isinstance(sib.tag, str)):
            run += 1
            best_run = max(best_run, run)
        else:
            run = 0
    return total * (1.0 + config.RUN_BONUS * min(best_run, 8))


def boiler_ratio(el) -> float:
    """Share of the container's own short lines that are chrome strings."""
    lines = [l.strip() for l in el.text_content().split('\n') if l.strip()]
    short = [l for l in lines if len(l) < 70]
    if not short:
        return 0.0
    hits = sum(1 for l in short if BOILER_RE.search(l))
    return hits / len(short)


def select_generic(root, html_str: str = '') -> str:
    """Prose scoring + link density + landmarks + title alignment.

    Returns the strategy label used.
    """
    body = root.find('.//body')
    if body is None:
        body = root

    for el in list(body.iter()):
        if isinstance(el.tag, str) and (el.tag in ('nav', 'form') or is_chrome(el)):
            el.set('__chrome', '1')

    titles = _title_tokens(page_title(root)) | _title_tokens(og_title(html_str))
    types = ' '.join(jsonld_types(html_str)).lower()
    article_type = any(t in types for t in ('article', 'newsarticle', 'blogposting',
                                            'discussionforumposting', 'howto',
                                            'medicalwebpage', 'qa'))
    total_text = max(text_len(body), 1)

    cands = []
    for el in body.iter():
        if not isinstance(el.tag, str) or hidden(el) or el.get('__chrome'):
            continue
        if el.tag not in CONTENT_TAGS:
            continue
        tl = text_len(el)
        if tl < 120:
            continue
        ld = link_density(el)
        if ld > 0.85:
            continue
        ntags = max(sum(1 for x in el.iter() if isinstance(x.tag, str)), 1)
        prose = prose_score(el)

        score = config.W_PROSE * prose + config.W_DENSITY * tl * (1.0 - ld)
        score *= 1.0 + 0.6 * min(1.0, tl / (ntags * 10))
        # specificity: a container holding (nearly) the whole page is not an answer,
        # it is just the page. Favour the tightest container that still holds the prose.
        share = tl / total_text
        score *= (share ** 0.7) if share < 0.95 else 0.15
        score += 400.0 * landmark_score(el)
        score *= 1.0 - config.BOILER_PENALTY * boiler_ratio(el)
        if article_type:
            score *= 1.15
        toks = semantic_tokens(el)
        if toks & {'article', 'post', 'entry', 'story', 'content', 'prose', 'body'}:
            score *= 1.4
        # title alignment: does this subtree contain a heading close to the page title?
        if titles:
            for h in el.iter():
                if isinstance(h.tag, str) and h.tag in ('h1', 'h2', 'h3'):
                    ht = _title_tokens(h.text_content())
                    if ht and len(ht & titles) >= max(2, len(ht) // 2):
                        score *= 1.5
                        break
        cands.append((score, tl, el))

    cands.sort(key=lambda x: -x[0])
    chosen: list = []
    for score, tl, el in cands:
        if any(_is_descendant(el, c) for c in chosen):
            continue
        chosen = [c for c in chosen if not _is_descendant(c, el)]
        chosen.append(el)
        if len(chosen) >= 3:
            break

    for el in chosen:
        mark_subtree(el)

    strategy = 'generic-prose'
    if chosen:
        a = attrs_id(chosen[0])
        if CONTENT_KW.search(a):
            strategy = 'generic-landmark'

    # keep dense leaf blocks outside the chosen containers
    for el in body.iter():
        if not isinstance(el.tag, str) or hidden(el) or el.get('__keep') == '1':
            continue
        if _in_chrome(el):
            continue
        if el.tag not in ('p', 'li', 'pre', 'table', 'h1', 'h2', 'h3', 'h4',
                          'blockquote', 'dd', 'dt'):
            continue
        tl = text_len(el)
        if tl < 40:
            continue
        if link_density(el) > 0.5:
            continue
        el.set('__keep', '1')
        for a in el.iterancestors():
            a.set('__keep', '1')
    return strategy


def select_fallback(root) -> str:
    """Tier 3: the densest block that is not chrome."""
    body = root.find('.//body')
    if body is None:
        body = root
    best, best_score = None, -1.0
    for el in body.iter():
        if not isinstance(el.tag, str) or hidden(el) or el.get('__chrome'):
            continue
        if el.tag not in CONTENT_TAGS:
            continue
        tl = text_len(el)
        if tl < 80:
            continue
        score = prose_score(el) * (1.0 - link_density(el))
        if score > best_score:
            best, best_score = el, score
    if best is not None:
        mark_subtree(best)
        return 'fallback-densest'
    return 'fallback-empty'


# ------------------------------------------------------------------ helpers
def _is_descendant(a, b) -> bool:
    return any(p is b for p in a.iterancestors())


def _in_chrome(el) -> bool:
    return any(p.get('__chrome') == '1' for p in el.iterancestors())
