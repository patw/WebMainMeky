#!/usr/bin/env python3
"""Diagnose where rouge-5 is lost: recall (missing content) vs precision (junk).

Generic tier only. Reports precision/recall/length-ratio by difficulty stratum and
lists the worst pages so the failure pattern can be read, not guessed.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jieba import lcut
from rouge_score.rouge_scorer import _create_ngrams, _score_ngrams

from wmm import metrics
from wmm.pipeline import extract


def prec_rec(pred: str, gt: str):
    pred, gt = (pred or '').strip(), (gt or '').strip()
    if not pred and not gt:
        return 1.0, 1.0
    s = _score_ngrams(_create_ngrams(lcut(gt), 5), _create_ngrams(lcut(pred), 5))
    return s.precision, s.recall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--limit', type=int, default=250)
    ap.add_argument('--worst', type=int, default=12)
    args = ap.parse_args()

    rows = []
    for i, line in enumerate(open(args.path, encoding='utf-8', errors='replace')):
        if i >= args.limit:
            break
        d = json.loads(line)
        lvl = (d.get('meta') or {}).get('level') or 'unknown'
        res = extract(d.get('html') or '', url=d.get('url', ''), profile='gt', log=False)
        gt = d.get('groundtruth_content') or ''
        md = res['markdown']
        p, r = prec_rec(md, gt)
        rows.append({'i': i, 'url': d.get('url', ''), 'level': lvl,
                     'rouge5': metrics.rouge5(md, gt), 'prec': p, 'rec': r,
                     'ratio': len(md) / max(len(gt), 1), 'tier': res['tier'],
                     'validated': res['validated']})

    by = defaultdict(list)
    for r in rows:
        by[r['level']].append(r)

    print(f"{'stratum':10s} {'n':>4s} {'rouge5':>8s} {'prec':>8s} {'rec':>8s} {'len_ratio':>10s}")
    for lvl in sorted(by):
        v = by[lvl]
        print(f"{lvl:10s} {len(v):4d} "
              f"{statistics.mean(x['rouge5'] for x in v):8.4f} "
              f"{statistics.mean(x['prec'] for x in v):8.4f} "
              f"{statistics.mean(x['rec'] for x in v):8.4f} "
              f"{statistics.mean(min(x['ratio'], 5) for x in v):10.2f}")

    print('\nworst pages:')
    for r in sorted(rows, key=lambda x: x['rouge5'])[:args.worst]:
        print(f"  rouge5={r['rouge5']:.3f} prec={r['prec']:.3f} rec={r['rec']:.3f} "
              f"ratio={r['ratio']:.2f} {r['level']:6s} {r['url'][:60]}")

    low_rec = [r for r in rows if r['rec'] < 0.5]
    low_prec = [r for r in rows if r['prec'] < 0.5]
    print(f"\npages with recall<0.5: {len(low_rec)}   precision<0.5: {len(low_prec)}")
    print(f"pages with ratio>2 (too much output): {sum(1 for r in rows if r['ratio'] > 2)}")
    print(f"pages with ratio<0.5 (too little): {sum(1 for r in rows if r['ratio'] < 0.5)}")


if __name__ == '__main__':
    main()
