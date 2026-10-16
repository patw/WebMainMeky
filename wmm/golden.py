"""Golden set: hand-checkable reference pages, and the regression gate they enforce.

A rule may not become active until it has been checked against the golden pages whose
layout signature it claims to match. This is what stops a rule that was authored from
one page from firing on a layout it was never meant for.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import metrics, select, serialize, validate as gate
from .signature import compute_signature

MIN_GOLDEN_CHARS = 400
MIN_GOLDEN_SCORE = 0.55


def build_from_jsonl(path, limit: int = 60, per_domain: int = 1, skip: int = 0) -> list[dict]:
    """Pick clean labelled pages: gate-passing, non-trivial, spread over domains.

    skip lets the golden set be drawn from a slice disjoint from the eval pages."""
    from urllib.parse import urlparse
    per_count = defaultdict(int)
    out = []
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for i, line in enumerate(fh):
            if i < skip:
                continue
            if i >= skip + limit:
                break
            d = json.loads(line)
            html, gt = d.get('html') or '', d.get('groundtruth_content') or ''
            url = d.get('url', '')
            host = (urlparse(url).netloc or '').lower()
            host = host[4:] if host.startswith('www.') else host
            if len(gt) < MIN_GOLDEN_CHARS:
                continue
            if not gate.validate(gt)['ok']:
                continue
            if per_count[host] >= per_domain:
                continue
            per_count[host] += 1
            out.append({'url': url, 'html': html, 'markdown': gt,
                        'domain': host,
                        'level': (d.get('meta') or {}).get('level') or 'unknown'})
            if len(out) >= 60:
                break
    return out


def store_golden(store, pages) -> int:
    for p in pages:
        store.add_golden(p['url'], p['html'], p['markdown'])
    return len(pages)


def check_rule(store, rule: dict, limit: int = 60) -> dict:
    """Apply a rule to every golden page it claims to match and score the output.

    Returns {'checked': n, 'mean': float, 'worst': float, 'ok': bool, 'detail': [...]}.
    A rule with no golden match is judged on its own example page only, which is
    weak evidence - callers should treat checked==0 as 'not verified'.
    """
    keys = {rule.get('signature')}
    detail = []
    for row in store.golden_pages(limit=limit):
        html = row.get('html') or ''
        sig = compute_signature(select.parse_html(html))
        if (sig.fine or sig.coarse) not in keys and (sig.family or sig.coarse) not in keys:
            continue
        root = select.parse_html(html)
        hits = select.apply_rule(root, rule.get('include_xpaths'), rule.get('exclude_xpaths'))
        if not hits:
            md = ''
        else:
            select.prune_unmarked(root)
            md = serialize.render(root, profile=rule.get('profile') or 'gt', filter_mode=True)
        s = metrics.score(md, row.get('markdown') or '')
        detail.append({'url': row.get('url'), 'rouge5': s['rouge5'],
                       'overall': s['overall']})
    if not detail:
        return {'checked': 0, 'mean': None, 'worst': None, 'ok': False, 'detail': []}
    scores = [d['rouge5'] for d in detail if d['rouge5'] is not None]
    mean = sum(scores) / len(scores) if scores else 0.0
    worst = min(scores) if scores else 0.0
    return {'checked': len(detail), 'mean': round(mean, 4), 'worst': round(worst, 4),
            'ok': mean >= MIN_GOLDEN_SCORE, 'detail': detail}
