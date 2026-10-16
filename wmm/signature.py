"""Layout signature: a stable fingerprint of a page's block structure.

Two levels:
  coarse - tag shape only (depth + tag sequence + counts). Transfers across sites
           that share a template, which is where the leverage is.
  fine   - tag shape + semantic class/id tokens (generated hashes stripped).
           More specific, higher confidence, less transfer.

Lookup order is fine first, then coarse. Never keyed by domain.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .dom import BLOCK_TAGS, HEADINGS, block_elements, hidden, semantic_tokens, text_len

CAP = 80          # blocks considered in the fingerprint
MIN_BLOCKS = 6    # below this the signature is not trustworthy


@dataclass
class Signature:
    fine: str
    coarse: str
    family: str
    n_blocks: int
    n_headings: int
    n_tables: int
    n_lists: int
    n_code: int
    n_paras: int
    body_chars: int
    flags: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d.pop('tokens', None)
        return d

    @property
    def usable(self) -> bool:
        return self.n_blocks >= MIN_BLOCKS


def _h(parts: list[str]) -> str:
    return hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()[:20]


def _bucket(n: int, edges=(0, 3, 8, 20, 60)) -> int:
    for i, e in enumerate(edges):
        if n <= e:
            return i
    return len(edges)


def compute_signature(root) -> Signature:
    coarse: list[str] = []
    fine: list[str] = []
    fam: list[str] = []
    n_headings = n_tables = n_lists = n_code = n_paras = 0
    body_chars = 0
    seen = 0
    shell: list[str] = []

    body = root.find('.//body')
    scope = body if body is not None else root

    for el, depth in block_elements(scope):
        if hidden(el):
            continue
        tag = el.tag
        if tag in HEADINGS:
            n_headings += 1
        elif tag == 'table':
            n_tables += 1
        elif tag in ('ul', 'ol'):
            n_lists += 1
        elif tag == 'pre':
            n_code += 1
        elif tag == 'p':
            n_paras += 1
            body_chars += text_len(el)

        if depth <= 3 and tag in ('div', 'section', 'article', 'main', 'header',
                                  'footer', 'aside', 'nav', 'table', 'ul', 'ol',
                                  'form', 'span'):
            shell.append(f'{depth}:{tag}')

        if seen >= CAP:
            seen += 1
            continue
        seen += 1
        coarse.append(f'{depth}:{tag}')
        toks = sorted(semantic_tokens(el))[:2]
        fine.append(f'{depth}:{tag}:' + '.'.join(toks))

    n_blocks = seen
    # family = layout profile: bucketed counts + landmark flags + the outer shell.
    # Order-independent and text-independent, so it groups pages built from the
    # same template - this is the level where rule support accumulates.
    fam_flags = []
    for probe, name in (('article', 'article'), ('main', 'main'), ('nav', 'nav'),
                        ('aside', 'aside'), ('footer', 'footer'), ('header', 'header'),
                        ('form', 'form'), ('table', 'table')):
            if root.find(f'.//{probe}') is not None:
                fam_flags.append(name)
    # counts only: the coarsest useful key. Adding flags/shell made every page its
    # own family on WebMainBench (272 unique families per 300 pages), which stops
    # support from ever accumulating and no rule ever promotes.
    fam = [
        f'p{_bucket(n_paras)}', f'h{_bucket(n_headings)}', f't{_bucket(n_tables)}',
        f'l{_bucket(n_lists)}', f'c{_bucket(n_code)}',
        f'v{_bucket(body_chars, (300, 1200, 4000, 15000))}',
    ]

    return Signature(
        fine=_h(fine) if n_blocks >= MIN_BLOCKS else '',
        coarse=_h(coarse) if n_blocks >= MIN_BLOCKS else '',
        family=_h(fam) if n_blocks >= MIN_BLOCKS else '',
        n_blocks=n_blocks,
        n_headings=n_headings,
        n_tables=n_tables,
        n_lists=n_lists,
        n_code=n_code,
        n_paras=n_paras,
        body_chars=body_chars,
        flags=sorted(fam_flags),
        tokens=coarse[:12],
    )


def signature_key(sig: Signature) -> str:
    """Primary lookup key: fine when available, else coarse."""
    return sig.fine or sig.coarse


def candidate_keys(sig: Signature) -> list[str]:
    keys = []
    for k in (sig.fine, sig.coarse, sig.family):
        if k:
            keys.append(k)
    return keys


def shape_summary(sig: Signature) -> str:
    return json.dumps({
        'blocks': sig.n_blocks, 'headings': sig.n_headings, 'tables': sig.n_tables,
        'lists': sig.n_lists, 'code': sig.n_code, 'paras': sig.n_paras,
        'chars': sig.body_chars,
    }, sort_keys=True)
