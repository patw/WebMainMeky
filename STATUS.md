# STATUS — v0.4.0 (2026-10-15, published)

Published at https://github.com/patw/WebMainMeky. The seeded rule store (210 rules,
184 active, 60 golden pages) ships in `store/` and is the default `WMM_DATA_DIR`, so a
fresh install reproduces the in-domain and golden numbers below with no setup.
Dataset for the eval scripts: `scripts/fetch_dataset.sh`.

Main-content extraction service (FastAPI + moofile).
32 tests pass. Every number below is measured on the WebMainBench 545 subset
(`data/WebMainBench_545.jsonl`) by the scripts in `scripts/`.

## v0.4.0 changes

1. **Output trimming** (`wmm/trim.py`): stop at commentary/recommendation headings
   once the article is substantial; drop link-list blocks; drop short sentence-less
   blocks. Switches in config, ablated by `scripts/ablate_trim.py`.
2. **Line-level boilerplate filter** (`wmm/clean.py`): chrome strings that live
   *inside* the content subtree (per-post toolbars, tag lists, pagination) removed by
   line shape, with document-wide repeat counting.
3. **Prose-based selection** (`wmm/select.py`): scoring now rewards long prose and
   runs of consecutive prose siblings, and penalizes containers whose short lines are
   chrome strings.
4. **Golden set + regression gate** (`wmm/golden.py`): 60 hand-checkable reference
   pages, drawn from a slice disjoint from the eval pages. A rule cannot go active if
   it demonstrably mangles a golden page sharing its layout signature.
5. New scripts: `scripts/diagnose.py` (precision/recall/length-ratio per stratum),
   `scripts/ablate_trim.py`, `scripts/build_golden.py`.

## Trim ablation (250 pages, generic tier only, in-domain)

| config | rouge5 | hard | mid | simple | overall |
|---|---|---|---|---|---|
| no_trim | 0.6585 | 0.5260 | 0.6814 | 0.7611 | 0.5251 |
| stop_only | 0.6683 | 0.5355 | 0.6983 | 0.7618 | 0.5360 |
| linklist_only | 0.6585 | 0.5260 | 0.6814 | 0.7611 | 0.5251 |
| lowvalue_only | 0.6662 | 0.5309 | 0.6867 | 0.7749 | 0.5319 |
| all (stop@600) | 0.6761 | 0.5404 | 0.7039 | 0.7755 | 0.5425 |
| **all (stop@300)** | **0.6767** | 0.5398 | **0.7058** | **0.7755** | **0.5444** |
| all (stop@1200) | 0.6727 | 0.5348 | 0.6997 | 0.7755 | 0.5412 |

All three trims contribute; the link-list rule is the weakest on its own and the
strongest in combination. Stop threshold 300 chars beats 600 and 1200.

## Held-out CV (250 pages, 206 domains, 5 folds) — the generalization number

| metric | v0.2.0 | v0.4.0 | delta |
|---|---|---|---|
| rouge5 | 0.6380 ±0.053 | **0.6611 ±0.035** | +0.023 |
| text_edit | 0.5781 | 0.6054 | +0.027 |
| code_edit | 0.9801 | 0.9761 | -0.004 |
| formula_edit | 0.2502 | 0.2289 | -0.021 |
| table_edit | 0.1331 | 0.1331 | 0 |
| **overall** | 0.5548 ±0.031 | **0.5800 ±0.019** | **+0.025** |
| rule hit | 9.0% | 9.8% | +0.8pt |
| validated | 91.2% | 93.8% | +2.6pt |

By stratum (held-out): simple 0.6556→0.6864, mid 0.5233→0.5651, hard 0.4395→0.4282.

## In-domain eval (100 seeded pages)

```
tiers: rule 66 / generic 33 / fallback 1     rule hit 66%   validated 93%
rouge5 0.7013  text 0.6726  code 0.9844  formula 0.2656  table 0.1994  overall 0.6554
per tier rouge5: rule 0.7384   generic 0.6485
```

## Golden set (60 pages, disjoint from eval pages, hard-skewed)

```
rouge5 0.6859   text 0.4865   code 0.6972   formula 0.1455   table 0.3568   overall 0.5081
```

The golden gate blocked 3 of 187 promotable rules (184 active). It is cheap insurance
against rules that were authored from one page and fire on layouts they never saw.

## Where the score is lost (measured, 250 pages)

| stratum | rouge5 | precision | recall | length ratio |
|---|---|---|---|---|
| hard | 0.5178 | 0.4642 | 0.7411 | 2.08 |
| mid | 0.6563 | 0.6074 | 0.7911 | 1.52 |
| simple | 0.7509 | 0.7215 | 0.8256 | 1.28 |

Precision, not recall, is the loss, and hard pages emit ~2x the ground-truth length.
I tested the obvious hypothesis and it is **wrong**: suppressing reply/comment/answer
containers on hard pages moved rouge5 0.5178 → 0.5177 (no effect), even though 21 of
55 hard pages carry such containers. The over-emission is diffuse chrome spread
through the content subtree, not one identifiable reply region. No rule was added for
it; the line-level boilerplate filter is what currently handles it.

## Benchmark position (published fine-grained overall on the 545)

mineru-html 0.8256 > **WebMainMeky held-out 0.5800** > magic-html 0.4996 >
trafilatura-md 0.4013 > resiliparse 0.2898.

Caveat: training rules are induced from the benchmark's own `cc-select` annotations on
*other* domains. No page overlap, no domain overlap - no memorization - but supervised
by the key. The zero-supervision reference (no rules at all, 250 pages) is
rouge5 0.6458 / overall 0.5583, which is within the CV noise of the held-out number:
**at 1.4 pages per domain the rule memory is not what is carrying the score.**

## Reproduce

```bash
cd WebMainMeky
.venv/bin/python -m pytest tests -q                                   # 32 tests
.venv/bin/python scripts/ablate_trim.py --path data/WebMainBench_545.jsonl --limit 250
.venv/bin/python scripts/cv_wmb.py --path data/WebMainBench_545.jsonl --limit 250 --folds 5
mkdir -p /tmp/v04
.venv/bin/python scripts/build_golden.py --path data/WebMainBench_545.jsonl --skip 420 --limit 125 --db /tmp/v04
.venv/bin/python scripts/seed_wmb.py  --path data/WebMainBench_545.jsonl --limit 300 --db /tmp/v04
.venv/bin/python scripts/eval_wmb.py  --path data/WebMainBench_545.jsonl --limit 100 --db /tmp/v04
.venv/bin/python scripts/diagnose.py  --path data/WebMainBench_545.jsonl --limit 250
```

## Next

1. Hard stratum precision (0.464) is the whole remaining gap. It needs content-region
   boundary detection, not more keyword rules - keyword suppression measured as a no-op.
2. formula_edit is format-calibration bound (0.23 held-out): the GT's escaped-dollar
   convention is only partially reproducible.
3. Compaction: 210 signatures from 300 pages, most with support 1. Merge and prune.
4. Measure the rule memory where repetition exists - a multi-page crawl of a few sites.
