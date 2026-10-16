#!/usr/bin/env python3
"""Seed the rule store by inducing selectors from labelled pages (no LLM).

Input: JSONL with fields html, url, groundtruth_content (WebMainBench shape).
The cc-select="true" annotations say which nodes are content; wmm.seed turns
those into anchored, reusable XPath selectors, groups them by layout signature,
and the validation gate decides which ones earn promotion to active.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm.seed import seed_from_jsonl
from wmm.store import Store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--profile', default='gt')
    ap.add_argument('--db', default=None)
    args = ap.parse_args()

    store = Store(Path(args.db)) if args.db else Store()
    tally = seed_from_jsonl(args.path, store, limit=args.limit, profile=args.profile,
                            report_every=100)
    print('tally:', tally)
    print('store:', store.stats())
    store.close()


if __name__ == '__main__':
    main()
