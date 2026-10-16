#!/usr/bin/env python3
"""Ablate the trimming switches, per difficulty stratum, on the generic tier.

Each configuration runs in a subprocess so wmm.config picks up the env switches.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(__file__).resolve().parent.parent

CONFIGS = {
    'no_trim':        {'WMM_TRIM_STOP': '0', 'WMM_TRIM_LINKLIST': '0', 'WMM_TRIM_LOWVALUE': '0'},
    'stop_only':      {'WMM_TRIM_STOP': '1', 'WMM_TRIM_LINKLIST': '0', 'WMM_TRIM_LOWVALUE': '0'},
    'linklist_only':  {'WMM_TRIM_STOP': '0', 'WMM_TRIM_LINKLIST': '1', 'WMM_TRIM_LOWVALUE': '0'},
    'lowvalue_only':  {'WMM_TRIM_STOP': '0', 'WMM_TRIM_LINKLIST': '0', 'WMM_TRIM_LOWVALUE': '1'},
    'all':            {'WMM_TRIM_STOP': '1', 'WMM_TRIM_LINKLIST': '1', 'WMM_TRIM_LOWVALUE': '1'},
    'all_stop300':    {'WMM_TRIM_STOP': '1', 'WMM_TRIM_LINKLIST': '1', 'WMM_TRIM_LOWVALUE': '1',
                       'WMM_STOP_AFTER_CHARS': '300'},
    'all_stop1200':   {'WMM_TRIM_STOP': '1', 'WMM_TRIM_LINKLIST': '1', 'WMM_TRIM_LOWVALUE': '1',
                       'WMM_STOP_AFTER_CHARS': '1200'},
}

RUNNER = r'''
import json, sys
sys.path.insert(0, ".")
from wmm.pipeline import extract
from wmm import metrics
out = []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    d = json.loads(line)
    lvl = (d.get("meta") or {}).get("level") or "unknown"
    res = extract(d.get("html") or "", url=d.get("url", ""), profile="gt", log=False)
    s = metrics.score(res["markdown"], d.get("groundtruth_content") or "")
    out.append((lvl, s.get("rouge5"), s.get("overall")))
print(json.dumps(out))
'''


def run(path, limit, env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    p = subprocess.run([sys.executable, '-c', RUNNER, path, str(limit)],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    if p.returncode:
        raise SystemExit(p.stderr[-600:])
    return json.loads(p.stdout.strip().split('\n')[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--limit', type=int, default=250)
    args = ap.parse_args()

    print(f"{'config':14s} {'rouge5':>8s} {'hard':>8s} {'mid':>8s} {'simple':>8s} {'overall':>8s}")
    for name, env_extra in CONFIGS.items():
        rows = run(args.path, args.limit, env_extra)
        by = defaultdict(list)
        ov, allr = [], []
        for lvl, r, o in rows:
            if r is not None:
                by[lvl].append(r)
                allr.append(r)
            if o is not None:
                ov.append(o)
        cells = [f'{statistics.mean(allr):8.4f}']
        for lvl in ('hard', 'mid', 'simple'):
            v = by.get(lvl) or [0]
            cells.append(f'{statistics.mean(v):8.4f}')
        cells.append(f'{statistics.mean(ov) if ov else 0:8.4f}')
        print(f'{name:14s} ' + ' '.join(cells), flush=True)


if __name__ == '__main__':
    main()
