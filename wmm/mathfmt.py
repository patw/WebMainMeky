"""Math-aware dollar handling.

The ground-truth markdown escapes currency dollars as backslash-dollar (the
generator was html2text), while genuine formulas keep $...$. The metric's formula splitter
only matches unescaped $...$, so a serializer that escapes everything scores 0
on real formulas and one that escapes nothing scores 0 on currency.

Rule implemented here is the deterministic version of the criteria written in
webmainbench/metrics/formula_extractor.py's own prompt: keep spans containing
math symbols / Greek letters / LaTeX commands, drop pure numbers and currency.
"""
from __future__ import annotations

import re

MATH_SYM = set('+=<>^_{}∑∫∂√±×÷≤≥∞≈≠%‰αβγδθλμπσωΔΣΩ')
MATH_CMD = re.compile(r'\\(frac|sum|int|sqrt|alpha|beta|gamma|delta|theta|lambda|mu|'
                      r'pi|sigma|omega|sin|cos|tan|log|ln|exp|lim|infty|cdot|times|'
                      r'leq|geq|neq|approx|partial|nabla|mathbb|mathcal|vec|hat)')
CURRENCY = re.compile(r'^[\d,.\s]+$')
OP_AROUND = re.compile(r'\b[a-zA-Z]\s*[=+\-*/^]\s*[a-zA-Z0-9]')


def looks_math(s: str) -> bool:
    t = (s or '').strip()
    if not t or len(t) > 200:
        return False
    if CURRENCY.match(t):
        return False
    if any(ch in MATH_SYM for ch in t):
        return True
    if MATH_CMD.search(t):
        return True
    if OP_AROUND.search(t):
        return True
    return False


def escape_dollars(md: str) -> str:
    """Escape every $, then un-escape the pairs that look like real math."""
    md = md.replace('\\$', '$').replace('$', '\\$')

    def repl(m):
        inner = m.group(1)
        return f'${inner}$' if looks_math(inner) else m.group(0)

    # inner may not contain '$', so pairs are always adjacent delimiters - a
    # currency span can never pair with a formula span
    return re.sub(r'\\\$(?!\s)([^$]+?)(?<!\s)\\\$', repl, md, flags=re.S)
