#!/usr/bin/env python3
"""Measure the service against labelled pages.

Reports: tier distribution, rule hit rate, validation pass rate, and scores against
the human ground truth. Pass --holdout-domain <d> (repeatable) to exclude those
domains from seeding - that is the generalization test: rules learned on one set of
domains, measured on unseen ones.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm import metrics
from wmm.pipeline import extract
from wmm.store import Store


def domain(url: str) -> str:
    h = (urlparse(url).netloc or '').lower()
    return h[4:] if h.startswith('www.') else h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--limit', type=int, default=60)
    ap.add_argument('--skip', type=int, default=0)
    ap.add_argument('--profile', default='gt')
    ap.add_argument('--db', default=None)
    ap.add_argument('--report-every', type=int, default=25)
    args = ap.parse_args()

    store = Store(Path(args.db)) if args.db else Store()
    tiers = Counter()
    scores = []
    validated = 0
    rule_hits = 0
    per_tier_scores = {}

    with open(args.path, 'r', encoding='utf-8', errors='replace') as fh:
        for i, line in enumerate(fh):
            if i < args.skip:
                continue
            if i >= args.skip + args.limit:
                break
            d = json.loads(line)
            html, gt, url = d.get('html') or '', d.get('groundtruth_content') or '', d.get('url', '')
            res = extract(html, url=url, profile=args.profile, store=store)
            tiers[res['tier']] += 1
            if res['rule_id']:
                rule_hits += 1
            if res['validated']:
                validated += 1
            s = metrics.score(res['markdown'], gt)
            s['tier'] = res['tier']
            scores.append(s)
            per_tier_scores.setdefault(res['tier'], []).append(s)
            if (i + 1) % args.report_every == 0:
                print(f'  [{i + 1}] tiers={dict(tiers)} validated={validated}', flush=True)

    n = len(scores)
    print('\n=== summary over', n, 'pages ===')
    print('tiers:', dict(tiers))
    print(f'rule_hits={rule_hits} ({100 * rule_hits / max(n, 1):.0f}%)  '
          f'validated={validated} ({100 * validated / max(n, 1):.0f}%)')
    keys = ['rouge5', 'text_edit', 'code_edit', 'formula_edit', 'table_edit', 'overall']
    print(f"{'metric':14s} {'ALL':>8s} " + ' '.join(f'{t:>10s}' for t in per_tier_scores))
    for k in keys:
        allv = [s[k] for s in scores if s.get(k) is not None]
        row = f'{k:14s} {sum(allv) / max(len(allv), 1):8.4f} '
        for t in per_tier_scores:
            v = [s[k] for s in per_tier_scores[t] if s.get(k) is not None]
            row += f'{(sum(v) / len(v)) if v else 0:10.4f} '
        print(row)

    # golden set regression: the same pipeline, scored on the stored reference pages
    golden = store.golden_pages(limit=200)
    if golden:
        g_scores = []
        for g in golden:
            res = extract(g.get('html') or '', url=g.get('url', ''),
                          profile=args.profile, store=store, log=False)
            g_scores.append(metrics.score(res['markdown'], g.get('markdown') or ''))
        print('\ngolden set ({} pages):'.format(len(golden)))
        for k in keys:
            v = [s[k] for s in g_scores if s.get(k) is not None]
            if v:
                print(f'  {k:14s} {sum(v) / len(v):8.4f}  (n={len(v)})')

    print('\nstore:', store.stats())
    store.close()


if __name__ == '__main__':
    main()
