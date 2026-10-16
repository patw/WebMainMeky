#!/usr/bin/env python3
"""Run the LLM authoring loop over logged failures.

Episodes store a hash of the page, not the page itself, so this offline runner
matches episodes back to a labelled JSONL by html_hash and feeds the author the
real HTML. In production the background job re-fetches the URL instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm import author as A
from wmm.store import Store, html_hash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--limit', type=int, default=5)
    ap.add_argument('--db', default=None)
    args = ap.parse_args()

    store = Store(Path(args.db)) if args.db else Store()
    pages = {}
    with open(args.path, 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            d = json.loads(line)
            pages[html_hash(d.get('html') or '')] = d

    pending = store.pending_authoring(limit=200)
    print('pending episodes:', len(pending))
    done = 0
    for ep in pending:
        if done >= args.limit:
            break
        d = pages.get(ep.get('html_hash'))
        if not d:
            continue
        ep = dict(ep)
        ep['markdown_preview'] = ''
        res = A.author_rule(store, ep, d['html'])
        done += 1
        if res.get('ok'):
            rule = res['rule']
            print(f"  authored url={ep.get('url','')[:50]} validated={res['validated']} "
                  f"status={rule['status']} support={rule['support']} conf={rule['confidence']}")
            print(f"    include={res['include'][:2]}")
        else:
            print(f"  failed url={ep.get('url','')[:50]} reason={res.get('reason')}")
    print('authored for', done, 'episodes')
    print('store:', store.stats())
    store.close()


if __name__ == '__main__':
    main()
