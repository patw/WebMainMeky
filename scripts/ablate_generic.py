#!/usr/bin/env python3
"""Sweep the generic-tier scoring weights, reported per difficulty stratum.

Generic tier only (no rule store), so every configuration is measured on the same
selection problem. Weights come from the environment (see wmm/config.py), which lets
this script run each setting in a subprocess with a clean config.
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

from wmm import metrics
from wmm.pipeline import extract

CONFIGS = {
    'density_only':      {'WMM_W_PROSE': '0.0',  'WMM_W_DENSITY': '1.0'},
    'balanced':          {'WMM_W_PROSE': '0.55', 'WMM_W_DENSITY': '0.45'},
    'prose_heavy':       {'WMM_W_PROSE': '0.8',  'WMM_W_DENSITY': '0.2'},
    'prose_only':        {'WMM_W_PROSE': '1.0',  'WMM_W_DENSITY': '0.0'},
    'no_boiler_penalty': {'WMM_W_PROSE': '0.55', 'WMM_W_DENSITY': '0.45',
                          'WMM_BOILER_PENALTY': '0.0'},
    'no_run_bonus':      {'WMM_W_PROSE': '0.55', 'WMM_W_DENSITY': '0.45',
                          'WMM_RUN_BONUS': '0.0'},
    'min_prose_60':      {'WMM_W_PROSE': '0.55', 'WMM_W_DENSITY': '0.45',
                          'WMM_MIN_PROSE': '60'},
}

RUNNER = r'''
import json, sys, statistics
sys.path.insert(0, ".")
from wmm.pipeline import extract
from wmm import metrics
from urllib.parse import urlparse
out = []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    d = json.loads(line)
    lvl = (d.get("meta") or {}).get("level") or "unknown"
    res = extract(d.get("html") or "", url=d.get("url", ""), profile="gt", log=False)
    s = metrics.score(res["markdown"], d.get("groundtruth_content") or "")
    out.append((lvl, s.get("rouge5"), s.get("overall")))
print(json.dumps(out))
'''


def run(path: str, limit: int, env_extra: dict) -> list:
    env = dict(os.environ)
    env.update(env_extra)
    p = subprocess.run([sys.executable, '-c', RUNNER, path, str(limit)],
                       capture_output=True, text=True, env=env, cwd=str(Path(__file__).resolve().parent.parent))
    if p.returncode != 0:
        raise SystemExit(p.stderr[-800:])
    return json.loads(p.stdout.strip().split('\n')[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--limit', type=int, default=250)
    args = ap.parse_args()

    print(f"{'config':18s} {'rouge5':>8s} {'hard':>8s} {'mid':>8s} {'simple':>8s} {'overall':>8s}")
    for name, env_extra in CONFIGS.items():
        rows = run(args.path, args.limit, env_extra)
        allr = [r for _, r, _ in rows if r is not None]
        by = defaultdict(list)
        ov = []
        for lvl, r, o in rows:
            if r is not None:
                by[lvl].append(r)
            if o is not None:
                ov.append(o)
        cells = [f'{statistics.mean(allr):8.4f}']
        for lvl in ('hard', 'mid', 'simple'):
            v = by.get(lvl) or [0]
            cells.append(f'{statistics.mean(v):8.4f}')
        cells.append(f'{statistics.mean(ov) if ov else 0:8.4f}')
        print(f'{name:18s} ' + ' '.join(cells), flush=True)


if __name__ == '__main__':
    main()
