#!/usr/bin/env python3
"""Build the golden set from labelled pages and store it.

The golden set is the regression reference: rules are checked against it before
promotion, and every eval run reports the score on it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm.golden import build_from_jsonl, store_golden
from wmm.store import Store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--skip', type=int, default=0)
    ap.add_argument('--per-domain', type=int, default=1)
    ap.add_argument('--db', default=None)
    args = ap.parse_args()

    pages = build_from_jsonl(args.path, limit=args.limit, per_domain=args.per_domain,
                             skip=args.skip)
    store = Store(Path(args.db)) if args.db else Store()
    n = store_golden(store, pages)
    print(f'golden pages stored: {n}')
    for p in pages[:8]:
        print(f"  {p['level']:8s} {p['url'][:70]}")
    print('store:', store.stats())
    store.close()


if __name__ == '__main__':
    main()
