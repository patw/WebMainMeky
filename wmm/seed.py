"""Rule induction from labelled pages: turn "these nodes are content" into a
reusable, anchored XPath and feed it through the store's promotion machinery.

No LLM. Used by scripts/seed_wmb.py and scripts/cv_wmb.py.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from . import serialize, select
from . import validate as gate
from .signature import compute_signature

SEMANTIC_TOKENS = {
    'article', 'post', 'entry', 'content', 'body', 'story', 'text', 'main',
    'detail', 'details', 'description', 'prose', 'readme', 'doc', 'paragraph',
    'post-content', 'post-body', 'entry-content', 'article-body', 'blog-post',
    'news-content', 'question-content', 'answer', 'thread', 'topic', 'wrapper',
    'container', 'inner', 'page', 'region',
}
ANCHOR_OK = {'article', 'main', 'section', 'div', 'td', 'form', 'table', 'aside',
             'li', 'span', 'p'}


def _tokens(el):
    raw = f"{el.get('class', '')} {el.get('id', '')}"
    return [t.strip().lower() for t in raw.split() if t.strip()]


def clean_id(el):
    i = el.get('id') or ''
    if not i or len(i) > 30:
        return None
    if re.search(r'\d{3,}', i) or re.search(r'[0-9a-f]{6,}', i, re.I):
        return None
    return i


def semantic_class(el):
    for tok in sorted(_tokens(el)):
        if tok in SEMANTIC_TOKENS:
            return tok
    return None


def unique_tag(el) -> bool:
    parent = el.getparent()
    if parent is None:
        return el.tag in ANCHOR_OK
    same = [c for c in parent.iterchildren() if isinstance(c.tag, str) and c.tag == el.tag]
    return len(same) == 1 and el.tag in ANCHOR_OK


def anchor_predicate(el):
    cid = clean_id(el)
    if cid:
        return f"[@id='{cid}']"
    tok = semantic_class(el)
    if tok:
        return f"[contains(@class,'{tok}')]"
    if unique_tag(el):
        return ''
    return None


def pos_index(el) -> int:
    parent = el.getparent()
    if parent is None:
        return 1
    n = 0
    for c in parent.iterchildren():
        if isinstance(c.tag, str) and c.tag == el.tag:
            n += 1
            if c is el:
                return n
    return 1


def anchored_selector(el, body):
    """(xpath, strength). The anchor is the deepest reusable predicate; positional
    steps are only allowed below it, where a template keeps them stable."""
    chain = []
    cur = el
    while cur is not None and cur is not body:
        chain.append(cur)
        cur = cur.getparent()
    if cur is not body or not chain:
        return '', 'none'
    chain.reverse()

    anchor_i = None
    for i, node in enumerate(chain):
        if anchor_predicate(node) is not None:
            anchor_i = i
    if anchor_i is None:
        steps = [f'{n.tag}[{pos_index(n)}]' for n in chain]
        return '//body/' + '/'.join(steps), 'positional'

    node = chain[anchor_i]
    head = f"//{node.tag}{anchor_predicate(node)}"
    tail = [f'{n.tag}[{pos_index(n)}]' for n in chain[anchor_i + 1:]]
    return '/'.join([head] + tail), 'anchored'


def lca(nodes):
    if not nodes:
        return None

    def ancestors(n):
        out = []
        while n is not None:
            out.append(n)
            n = n.getparent()
        return out

    paths = [ancestors(n) for n in nodes]
    common = set(paths[0])
    for p in paths[1:]:
        common &= set(p)
    if not common:
        return None
    depth_of = {id(n): len(ancestors(n)) for n in common}
    return max(common, key=lambda n: depth_of[id(n)])


def induce(html_str: str):
    """(selector, strength|reason) from cc-select annotations."""
    root = select.parse_html(html_str)
    body = root.find('.//body')
    if body is None:
        return None, 'no_body'
    selected = [e for e in root.iter()
                if isinstance(e.tag, str) and e.get('cc-select') == 'true']
    if not selected:
        return None, 'no_key'
    maximal = [e for e in selected
               if not (e.getparent() is not None and e.getparent().get('cc-select') == 'true')]
    node = lca(maximal)
    if node is None:
        return None, 'no_lca'
    if node is body:
        return None, 'lca_is_body'
    return anchored_selector(node, body)


def apply(html_str: str, selectors, profile: str = 'gt') -> str:
    root = select.parse_html(html_str)
    hits = select.apply_rule(root, selectors)
    if not hits:
        return ''
    select.prune_unmarked(root)
    return serialize.render(root, profile=profile, filter_mode=True)


def seed_from_jsonl(path, store, limit: int = 0, profile: str = 'gt',
                    exclude_domains=None, report_every: int = 0):
    """Induce + validate rules from a labelled JSONL. Returns a tally dict."""
    exclude = set(exclude_domains or ())
    groups = defaultdict(lambda: {'selectors': [], 'outcomes': [], 'pages': [],
                                  'strength': 'anchored', 'flags': []})
    tally = defaultdict(int)

    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            d = json.loads(line)
            html, url = d.get('html') or '', d.get('url', '')
            tally['pages'] += 1
            sig = compute_signature(select.parse_html(html))
            key = sig.family or sig.coarse
            if not key:
                tally['no_signature'] += 1
                continue
            sel, strength = induce(html)
            if not sel:
                tally[strength] += 1
                continue
            tally['inducible'] += 1
            tally[f'strength:{strength}'] += 1

            g = groups[key]
            if not g['selectors']:
                g['selectors'] = [sel]
                g['strength'] = strength
                g['flags'] = sig.flags
            md = apply(html, g['selectors'], profile)
            ok = gate.validate(md)['ok']
            g['outcomes'].append(ok)
            if ok:
                tally['validated'] += 1
            g['pages'].append(url)
            if report_every and (i + 1) % report_every == 0:
                print(f'  seeded {i + 1} pages, {len(groups)} signatures', flush=True)

    promoted = 0
    for key, g in groups.items():
        if not g['selectors']:
            continue
        ok_n = sum(1 for o in g['outcomes'] if o)
        rule = store.upsert_rule(signature=key, level='family',
                                 include_xpaths=g['selectors'],
                                 provenance='induced', profile=profile,
                                 url=g['pages'][0],
                                 notes=f"seed {len(g['outcomes'])} pages, "
                                       f"{ok_n} validated, {g['strength']}",
                                 flags=g.get('flags'))
        for ok in g['outcomes']:
            rule = store.record_outcome(rule['_id'], ok)
        if rule['status'] == 'active':
            promoted += 1
    tally['signatures'] = len(groups)
    tally['promoted'] = promoted
    return dict(tally)
