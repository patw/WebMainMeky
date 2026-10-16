# WebMainMeky

Main-content extraction as a service. **The request path is 100% mechanistic** —
deterministic DOM parsing, layout-signature lookup, rule application, serialization,
validation. No model runs when you call `/extract`.

An LLM is used in exactly one place: **mutating the rule store**. When the mechanistic
path fails a page, that failure is logged, and a background job asks a model to propose
XPath selectors for that page layout. The proposal is verified mechanically on the page,
stored as a *candidate*, and only promoted to *active* after it re-validates on more
pages and passes a golden-set regression check. The model never answers requests and
never touches output.

The effect is a service that gets broader coverage over time while staying fast,
deterministic, reproducible and offline at request time.

---

## Where it actually scores

Measured on the [WebMainBench](https://github.com/opendatalab/WebMainBench) 545-sample
subset, using this repo's own scripts (`scripts/cv_wmb.py`, `scripts/eval_wmb.py`).
Rouge-5 is jieba-tokenized 5-gram F1, the same construction the benchmark uses.

**Held-out domains** — rules induced from one set of domains, scored only on domains
never seen during seeding (250 pages, 206 domains, 5 folds). This is the number to
believe:

| metric | value |
|---|---|
| **rouge-5** | **0.6611 ± 0.035** |
| text_edit | 0.6054 ± 0.023 |
| code_edit | 0.9761 ± 0.030 |
| formula_edit | 0.2289 ± 0.132 |
| table_edit | 0.1331 ± 0.085 |
| overall | 0.5800 ± 0.019 |
| validation gate pass | 93.8% |
| rule hit rate | 9.8% |

By difficulty stratum (held-out rouge-5): simple **0.746**, mid **0.660**, hard **0.532**.

**In-domain** (100 pages whose domains were seeded): rouge-5 **0.7013**, overall 0.6554.
When a seeded rule fires, that tier scores rouge-5 **0.7384**.

**Golden set** (60 hand-checkable pages, drawn from a slice disjoint from the eval
pages): rouge-5 **0.6859**, overall 0.5081.

### Comparison with published systems

Fine-grained `overall` on the 545 subset, as published by the benchmark authors:

| system | overall | rouge-5 (headline metric) |
|---|---|---|
| mineru-html / Dripper (a 0.6B LM) | 0.8256 | 0.9098 |
| **WebMainMeky, held-out domains** | **0.5800** | **0.6611** |
| magic-html | 0.4996 | 0.7141 |
| trafilatura (markdown) | 0.4013 | 0.6397 |
| resiliparse | 0.2898 | 0.6311 |

Plain reading: **we beat every classical rule-based extractor in the paper and we are
well behind the learned system.** That is the honest position. The gap to the LM is
content *selection* on hard pages — forums, listings, Q&A — where "what counts as the
article" is a judgement about discourse, not a structural property.

### The number that should temper every claim above

Zero-supervision reference: run the service with an **empty rule store** on 250 pages →
rouge-5 **0.6458**, overall **0.5583**. That is within the cross-validation noise of the
held-out result. So on this benchmark **the rule memory is not what carries the score** —
selection heuristics and serialization conventions are.

Why: WebMainBench has ~1.4 pages per domain. A layout-signature memory needs repetition
to pay off, and this dataset barely has any. The memory is built for the case the
benchmark does not measure: crawling the same site many times.

---

## Honest notes on the benchmark itself

Two things about WebMainBench that materially affect any score, including ours:

1. **The benchmark ships its answer key.** Every row of `webmainbench.jsonl` contains
   `cc-select="true"` annotations on the human-labelled content nodes, and the scoring
   target `convert_main_content` ships in the same row. That target is
   `html2text(extract_main_html(html))` — a deterministic function of the key. A ~15-line
   script reproduces it at rouge-5 **0.9923** (measured, 30 full-dataset samples), versus
   0.9098 for the best published model. We consider that a benchmark defect, not a
   capability result, and **this project does not read `cc-select` at request time.**
2. **Training rules here are induced from those annotations on *other* domains.** No page
   and no domain overlaps between training and evaluation, so the held-out numbers are not
   page memorization and not domain memorization — but they are supervised by the
   benchmark's key. The zero-supervision reference above is the number to compare against
   if you want a fully unsupervised figure.

`scripts/seed_wmb.py` is a research tool for measuring the rule memory. It is not part of
the service and is not used at request time.

---

## How it works

```
POST /extract  {url | html, profile}
   -> fetch (optional) -> parse with recovery
   -> compute layout signature
   -> tier 1: promoted rule matched by signature
   -> tier 2: generic selection (prose scoring, link density, landmarks, title alignment)
   -> tier 3: fallback (densest block, low confidence)
   -> serialize to markdown (convention profile)
   -> validation gate: is this plausibly an article?
   -> pass: return.  fail: return best-effort AND queue a rule-authoring job.
```

Three tiers, in order of cost:

| tier | what it is | request-time cost |
|---|---|---|
| `rule` | promoted rule matched by layout signature | microseconds |
| `generic` | prose density + link density + landmarks + title alignment | milliseconds |
| `fallback` | densest block, low confidence | milliseconds |

**Rules are keyed by layout signature, never by domain.** Chrome (nav, header, footer,
ads) is the structure that repeats across a site's pages; content is the structure that
varies. A rule written against a layout shape covers every site built from that template.
A rule written against a domain name covers one site and dies at the next redesign.

### Rule lifecycle

`candidate` → `active` → `retired`.

- Inserted as a candidate with **zero support**. Support is earned only from recorded
  validation outcomes, never from the insert.
- Promotion bar by provenance: label-induced rules promote on **one** validated page,
  LLM-authored rules need **two**, human rules promote immediately.
- Promotion additionally requires passing the **golden regression gate**: the rule is
  applied to every golden page sharing its layout signature and must average rouge-5
  ≥ 0.55 on them. In the shipped store this blocked 3 of 187 promotable rules.
- Confidence below 0.35 after 10+ uses → retired, and retired rules are never matched.

### The validation gate

The gate is what closes the self-improving loop. Cheap deterministic checks on the
rendered markdown: length, sentence count, mean sentence length, link density, nav-word
density, script consistency. Without it, failures are invisible, the authoring path never
fires, and the service quietly returns garbage forever.

### Serialization profiles

The document model is built first (typed blocks), then rendered through a profile:

- `canonical` — clean GitHub-flavored markdown, links preserved. Use this for downstream
  consumption (RAG, summarization).
- `gt` — the shape WebMainBench's ground truth happens to take: links dropped, `$`
  escaped, pipe tables, fenced code. Use this for benchmark scoring.

Extraction quality and output format are separable axes. This benchmark only rewards the
second one, so keep both profiles and report both numbers.

---

## Install

```bash
git clone git@github.com:patw/WebMainMeky.git && cd WebMainMeky
cp .env.example .env          # set OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL
uv venv --python 3.12 .venv
uv pip install -e ".[dev,eval]"     # service deps + pytest + scoring deps
.venv/bin/python -m pytest tests -q      # 32 tests
```

`[dev]` = pytest, httpx (tests). `[eval]` = jieba, rouge-score, rapidfuzz (scoring
scripts). Plain `pip install -e .` gives you the service only.

Dependencies: fastapi, uvicorn, pydantic, lxml, requests, openai, moofile. No model, no
GPU, no embedding step.

The repo ships a seeded rule store in `store/` (210 rules, 184 active, 60 golden pages,
layout census). `WMM_DATA_DIR` defaults to `store`, so a fresh install is immediately
usable. Set `WMM_DATA_DIR=data` to start from an empty store.

## Run as a service

```bash
.venv/bin/uvicorn wmm.app:app --host 0.0.0.0 --port 8090
```

```bash
curl -s localhost:8090/extract -H 'content-type: application/json' \
  -d '{"url":"https://example.com/article","profile":"canonical"}'
```

| endpoint | purpose |
|---|---|
| `POST /extract` | `{url}` or raw `{html}`, `profile` = `canonical` \| `gt`. Deterministic. |
| `GET /stats` | rule counts, episode counts, golden count |
| `GET /rules?status=active` | inspect the rule store |
| `POST /rules` | add a rule by hand (`activate: true` to force) |
| `POST /rules/{id}/status` | `candidate` \| `active` \| `retired` |
| `GET /episodes/pending` | failures queued for rule authoring |
| `POST /author` | run rule authoring (`episode_id` = background job, `html` = inline) |
| `POST /golden`, `GET /golden` | regression reference pages |
| `POST /compact` | compact the moofile collections |
| `GET /health` | liveness + configured model |

`/extract` with a `url` uses plain HTTP with a 20 s timeout and a 6 MB cap. **No
JavaScript rendering.** Pages that need JS should be posted to `/extract` as raw HTML by
a renderer service; treat fetching as a separate component.

---

## Operating this as an agent

Everything below is safe to run unattended. The request path never calls a model, so
serving traffic costs nothing in inference. Model calls happen only in the authoring step,
which you schedule.

**1. Serve.**

```bash
.venv/bin/uvicorn wmm.app:app --host 0.0.0.0 --port 8090
```

**2. Watch the failure queue.** Every request is logged as an episode with its layout
signature, tier used, gate verdict and reasons.

```bash
curl -s localhost:8090/stats
curl -s localhost:8090/episodes/pending?limit=20
```

**3. Grow coverage.** Author rules for queued failures. This is the only step that
touches the LLM, and it is offline:

```bash
# offline runner: matches logged episodes back to a labelled JSONL by html hash
.venv/bin/python scripts/author_from_dataset.py --path data/pages.jsonl --limit 20

# or per-episode over HTTP (background job re-fetches the URL)
curl -s localhost:8090/author -H 'content-type: application/json' \
  -d '{"episode_id":"<id>"}'
```

Authoring is guarded: selectors containing positional indexes (`div[3]`), `text()`
predicates, or generated class hashes are rejected; the rule must reproduce valid output
on its own page before it is stored; promotion then requires re-validation plus the
golden gate. A bad model output cannot silently poison the store, but **it can waste
queue space** — watch `golden_checked` / `golden_mean` on promoted rules.

**4. Measure before and after every change.** Never ship a rule batch without these:

```bash
.venv/bin/python -m pytest tests -q                                        # behaviour
.venv/bin/python scripts/eval_wmb.py --path data/WMB545.jsonl --limit 100  # in-domain + golden
.venv/bin/python scripts/cv_wmb.py  --path data/WMB545.jsonl --limit 250 --folds 5
.venv/bin/python scripts/diagnose.py --path data/WMB545.jsonl --limit 250  # precision/recall by stratum
```

`cv_wmb.py` is the one that matters: it trains on one set of domains and scores on
unseen ones. A per-page score can be memorization; a held-out-domain score cannot.

**5. Maintain.**

```bash
curl -s -X POST localhost:8090/compact          # moofile compaction (dead records accumulate)
.venv/bin/python scripts/build_golden.py --path data/WMB545.jsonl --skip 420 --limit 125
```

Retire rules that stop firing. Merge near-duplicate signatures. An unbounded store turns
into first-match-wins plus latency plus collisions.

**Agent-facing invariants**

- Do not read `cc-select` at request time. It is the benchmark's answer key; using it
  makes the score meaningless.
- Do not promote a rule without a `golden_mean` ≥ 0.55, and treat `golden_checked == 0`
  as *unverified*, not as *passed*.
- Report two numbers: `canonical` profile for real use, `gt` profile for benchmark
  comparison. They are not the same measurement.
- Log every request: signature, rule hit, tier, gate verdict. Without that, "it gets
  smarter over time" is a feeling.

---

## Layout

```
wmm/
  config.py      .env loading, tunables, scoring weights, trim switches
  dom.py         parsing with recovery, token normalization, structural statistics
  signature.py   fine / coarse / family layout signatures
  select.py      tier 1-3 selection, marking, pruning
  serialize.py   DOM -> markdown, convention profiles, table grid, math escaping
  clean.py       line-level boilerplate filter
  trim.py        stop-headings, link lists, low-value blocks
  validate.py    the gate
  store.py       moofile collections: rules, episodes, golden, signatures
  golden.py      golden set + regression gate
  pipeline.py    the deterministic request path
  author.py      LLM rule authoring (off the hot path)
  seed.py        rule induction from labelled pages (research tool)
  metrics.py     local scoring
  app.py         FastAPI service
  fetch.py       URL -> HTML (capped, no JS)
scripts/
  seed_wmb.py  eval_wmb.py  cv_wmb.py  diagnose.py  ablate_trim.py
  ablate_generic.py  build_golden.py  author_from_dataset.py
tests/          32 tests, positive and negative controls
store/          shipped rule store: 184 active rules, 60 golden pages
STATUS.md       full ablation tables and reproduce commands
```

## Known limits (measured, not guessed)

1. **Hard pages are the whole remaining gap** — held-out rouge-5 0.532, precision 0.464,
   output ~2× ground-truth length. Tested suppressing reply/comment/answer containers on
   hard pages: 21 of 55 carry them, effect on rouge-5 was **0.5178 → 0.5177, i.e. zero**.
   The over-emission is diffuse chrome inside the content subtree; keyword suppression is
   the wrong tool. This needs content-boundary detection.
2. **`formula_edit` ~0.23.** The ground truth escapes `$` as `\$`; the `gt` profile
   reproduces that partially. Format calibration, not extraction.
3. **`table_edit` ~0.13.** Grid reconstruction (colspan/rowspan/header) scores 0.997–1.000
   where the ground truth has a table; the metric is dominated by false positives, which
   is why layout tables are suppressed to prose.
4. **Signature granularity limits promotion.** Fine and coarse block-sequence signatures
   produced 291 unique keys per 300 pages; counts-only ~221. Support rarely accumulates,
   which is why promotion is provenance-dependent rather than a fixed support bar.
5. **No JS rendering.**
6. **Rule memory is unproven on this benchmark** (see the zero-supervision reference).
   It needs a multi-page crawl of real sites to demonstrate value.

## Reproduce every number in this README

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python scripts/cv_wmb.py --path ~/scratch/wmb545.jsonl --limit 250 --folds 5
.venv/bin/python scripts/eval_wmb.py --path ~/scratch/wmb545.jsonl --limit 100
.venv/bin/python scripts/diagnose.py --path ~/scratch/wmb545.jsonl --limit 250
.venv/bin/python scripts/ablate_trim.py --path ~/scratch/wmb545.jsonl --limit 250
# zero-supervision reference:
mkdir -p /tmp/empty && .venv/bin/python scripts/eval_wmb.py \
    --path ~/scratch/wmb545.jsonl --limit 250 --db /tmp/empty
```

Dataset: `WebMainBench_545.jsonl` from
`https://huggingface.co/datasets/opendatalab/WebMainBench` (Apache-2.0). The rule store in
`store/` was induced from that dataset's annotations on domains that are excluded from the
held-out evaluation folds.

## License

MIT. The bundled rule store is derived from WebMainBench (Apache-2.0, opendatalab);
attribute it if you redistribute the store.
