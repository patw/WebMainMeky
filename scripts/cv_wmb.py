#!/usr/bin/env python3
"""Domain-grouped cross-validation: the honest generalization measurement.

Rules are induced from the pages of one set of domains and evaluated only on
pages from domains never seen during seeding. Any claim that layout-signature
rules generalize has to survive this; per-page scores do not, because a rule can
memorize a page.

Usage:
  .venv/bin/python scripts/cv_wmb.py --path ~/scratch/wmb545.jsonl --folds 5
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm import metrics
from wmm.pipeline import extract
from wmm.seed import seed_from_jsonl
from wmm.store import Store

METRICS = ['rouge5', 'text_edit', 'code_edit', 'formula_edit', 'table_edit', 'overall']


def domain(url: str) -> str:
    h = (urlparse(url or '').netloc or '').lower()
    return h[4:] if h.startswith('www.') else h


def load(path, limit):
    import json
    rows = []
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            d = json.loads(line)
            rows.append({'url': d.get('url', ''), 'html': d.get('html') or '',
                         'gt': d.get('groundtruth_content') or '',
                         'domain': domain(d.get('url', '')),
                         'level': (d.get('meta') or {}).get('level') or 'unknown'})
    return rows


def write_subset(rows, path):
    import json
    with open(path, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps({'html': r['html'], 'url': r['url'],
                                 'groundtruth_content': r['gt'],
                                 'meta': {'level': r['level']}}) + '\n')
    return str(path)


def score_rows(store, rows, profile):
    out = {'n': len(rows), 'rule_hits': 0, 'validated': 0, 'tiers': defaultdict(int)}
    per = {m: [] for m in METRICS}
    per_level = defaultdict(lambda: defaultdict(list))
    for r in rows:
        res = extract(r['html'], url=r['url'], profile=profile, store=store, log=False)
        out['tiers'][res['tier']] += 1
        if res['rule_id']:
            out['rule_hits'] += 1
        if res['validated']:
            out['validated'] += 1
        s = metrics.score(res['markdown'], r['gt'])
        for m in METRICS:
            if s.get(m) is not None:
                per[m].append(s[m])
                per_level[r['level']][m].append(s[m])
    out['means'] = {m: (sum(v) / len(v) if v else None) for m, v in per.items()}
    out['by_level'] = {lv: {m: (sum(v) / len(v) if v else None)
                            for m, v in d.items()} for lv, d in per_level.items()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--limit', type=int, default=300)
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--profile', default='gt')
    ap.add_argument('--workdir', default=None)
    args = ap.parse_args()

    work = Path(args.workdir) if args.workdir else Path(args.path).parent / 'cv_tmp'
    work.mkdir(parents=True, exist_ok=True)

    rows = load(args.path, args.limit)
    doms = sorted({r['domain'] for r in rows})
    folds = defaultdict(list)
    for i, d in enumerate(doms):
        folds[i % args.folds].append(d)
    print(f'{len(rows)} pages, {len(doms)} domains, {args.folds} folds '
          f'(sizes {[len(f) for f in folds.values()]})')

    fold_results = []
    for f, fold_doms in sorted(folds.items()):
        train = [r for r in rows if r['domain'] not in set(fold_doms)]
        test = [r for r in rows if r['domain'] in set(fold_doms)]
        db = work / f'fold{f}'
        os_remove(db)
        store = Store(db)
        try:
            train_path = write_subset(train, work / f'train{f}.jsonl')
            tally = seed_from_jsonl(train_path, store, profile=args.profile)
            res = score_rows(store, test, args.profile)
            res['fold'] = f
            res['train_pages'] = len(train)
            res['test_pages'] = len(test)
            res['promoted'] = tally.get('promoted', 0)
            fold_results.append(res)
            print(f"fold {f}: train={len(train)} test={len(test)} promoted={res['promoted']} "
                  f"rule_hit={res['rule_hits']}/{res['n']} "
                  f"rouge5={fmt(res['means']['rouge5'])} overall={fmt(res['means']['overall'])}",
                  flush=True)
        finally:
            store.close()

    print('\n=== held-out means over folds ===')
    for m in METRICS:
        vals = [r['means'][m] for r in fold_results if r['means'][m] is not None]
        if vals:
            sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
            print(f'{m:14s} {statistics.mean(vals):.4f} +/- {sd:.4f}')
    hits = [100 * r['rule_hits'] / max(r['n'], 1) for r in fold_results]
    val = [100 * r['validated'] / max(r['n'], 1) for r in fold_results]
    print(f'{"rule_hit%":14s} {statistics.mean(hits):.1f}   '
          f'{"validated%":14s} {statistics.mean(val):.1f}')

    print('\n=== by difficulty stratum (held-out) ===')
    levels = sorted({lv for r in fold_results for lv in r['by_level']})
    for lv in levels:
        parts = []
        for m in ['rouge5', 'overall']:
            vals = [r['by_level'][lv][m] for r in fold_results
                    if lv in r['by_level'] and r['by_level'][lv].get(m) is not None]
            if vals:
                parts.append(f'{m}={statistics.mean(vals):.4f}')
        n = sum(len([1 for r in fold_results if lv in r['by_level']]) for _ in [0])
        print(f'{lv:10s} ' + '  '.join(parts))


def os_remove(p: Path):
    import shutil
    if p.exists():
        shutil.rmtree(p)


def fmt(v):
    return 'n/a' if v is None else f'{v:.4f}'


if __name__ == '__main__':
    main()
