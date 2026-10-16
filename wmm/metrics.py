"""Local scoring, mirroring WebMainBench's metrics so the project can be measured
without importing the benchmark package.

  rouge5      - jieba-tokenized 5-gram F1 (same construction as the benchmark)
  text_edit   - 1 - levenshtein/max(len) on plain text (code/tables/formulas removed)
  code_edit   - same on fenced/indented code only
  table_edit  - same on markdown pipe tables only
  formula_edit- same on $...$ spans only
  overall     - mean of the sub-metrics that produced a score (empty on both sides
                is excluded, exactly as the benchmark does)
"""
from __future__ import annotations

import re

import jieba
from rapidfuzz.distance import Levenshtein
from rouge_score.rouge_scorer import _create_ngrams, _score_ngrams


def rouge5(prediction: str, target: str) -> float:
    prediction = (prediction or '').strip()
    target = (target or '').strip()
    if not target and not prediction:
        return 1.0
    tg = _create_ngrams(jieba.lcut(target), 5)
    pg = _create_ngrams(jieba.lcut(prediction), 5)
    return _score_ngrams(tg, pg).fmeasure


def edit_sim(pred: str, gt: str):
    """Returns None when both sides are empty (metric excluded from the mean)."""
    if not pred and not gt:
        return None
    d = Levenshtein.distance(pred, gt)
    return 1.0 - d / max(len(pred), len(gt), 1)


def _strip_code(md: str) -> str:
    md = re.sub(r'```.*?```', '', md, flags=re.S)
    return re.sub(r'`[^`]*`', '', md)


def split_text(md: str) -> str:
    md = _strip_code(md or '')
    md = re.sub(r'^\|.*\|$', '', md, flags=re.M)
    md = re.sub(r'\$\$.*?\$\$', '', md, flags=re.S)
    md = re.sub(r'\$[^$]*\$', '', md)
    return md.strip()


def split_code(md: str) -> str:
    blocks = re.findall(r'```[\s\S]*?```', md or '')
    out = ['\n'.join(b.split('\n')[1:-1]) for b in blocks]
    return '\n'.join(out).strip()


def split_tables(md: str) -> str:
    rows = [l.strip() for l in (md or '').split('\n') if re.match(r'^\|.*\|$', l.strip())]
    rows = [r for r in rows if not re.match(r'^\|[-:\s|]+\|$', r)]
    return '\n'.join(rows).strip()


def split_formulas(md: str) -> str:
    md = _strip_code(md or '')
    out = [m.group(1) for m in re.finditer(r'\$\$(.+?)\$\$', md, flags=re.S)]
    out += [m.group(1) for m in re.finditer(r'(?<!\\)\$([^$]+?)\$', md)]
    return '\n'.join(x.strip() for x in out if x.strip()).strip()


def score(pred: str, gt: str) -> dict:
    parts = {
        'text_edit': edit_sim(split_text(pred), split_text(gt)),
        'code_edit': edit_sim(split_code(pred), split_code(gt)),
        'table_edit': edit_sim(split_tables(pred), split_tables(gt)),
        'formula_edit': edit_sim(split_formulas(pred), split_formulas(gt)),
    }
    scored = [v for v in parts.values() if v is not None]
    parts['overall'] = sum(scored) / len(scored) if scored else None
    parts['rouge5'] = rouge5(pred, gt)
    return parts
