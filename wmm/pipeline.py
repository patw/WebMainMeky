"""The extraction pipeline. Deterministic, no network on the request path.

  signature -> tier 1 (promoted rule) -> tier 2 (generic) -> tier 3 (fallback)
  each tier's output goes through the validation gate; a failure logs an episode
  flagged needs_authoring, which is what the background authoring job consumes.
"""
from __future__ import annotations

import time

from . import serialize, select, validate as gate
from .signature import candidate_keys, compute_signature, shape_summary
from .store import Store, html_hash


def _attempt(html_str: str, mark, profile: str):
    """mark(root) -> strategy string; returns (markdown, strategy)."""
    root = select.parse_html(html_str)
    strategy = mark(root)
    select.prune_unmarked(root)
    return serialize.render(root, profile=profile, filter_mode=True), strategy


def extract(html_str: str, url: str = '', profile: str = 'canonical',
            store: Store | None = None, log: bool = True) -> dict:
    t0 = time.time()
    html_str = html_str or ''
    sig = compute_signature(select.parse_html(html_str))
    keys = candidate_keys(sig)
    hhash = html_hash(html_str)

    result = {
        'url': url,
        'html_hash': hhash,
        'profile': profile,
        'signature': {'fine': sig.fine, 'coarse': sig.coarse, **sig.as_dict()},
        'tier': None,
        'rule_id': None,
        'strategy': None,
        'validated': False,
        'validation': None,
        'markdown': '',
        'attempts': [],
    }

    # ---- tier 1: promoted layout rule
    if store is not None and keys:
        rule = store.find_rule(keys, flags=sig.flags)
        if rule:
            md = _apply_rule(html_str, rule, profile)
            v = gate.validate(md)
            result['attempts'].append({'tier': 'rule', 'rule_id': rule['_id'],
                                       'ok': v['ok'], 'reasons': v['reasons']})
            store.record_outcome(rule['_id'], v['ok'])
            if v['ok']:
                result.update(tier='rule', rule_id=rule['_id'], strategy='rule-hit',
                              validated=True, validation=v, markdown=md)
                return _finish(result, t0, store, log, sig)

    # ---- tier 2: generic selection
    root = select.parse_html(html_str)
    strategy = select.select_generic(root, html_str)
    select.prune_unmarked(root)
    md2 = serialize.render(root, profile=profile, filter_mode=True)
    v2 = gate.validate(md2)
    result['attempts'].append({'tier': 'generic', 'ok': v2['ok'], 'reasons': v2['reasons']})
    if v2['ok']:
        result.update(tier='generic', strategy=strategy, validated=True,
                      validation=v2, markdown=md2)
        return _finish(result, t0, store, log, sig)

    # ---- tier 3: fallback
    root = select.parse_html(html_str)
    strategy3 = select.select_fallback(root)
    select.prune_unmarked(root)
    md3 = serialize.render(root, profile=profile, filter_mode=True)
    v3 = gate.validate(md3)
    result['attempts'].append({'tier': 'fallback', 'ok': v3['ok'], 'reasons': v3['reasons']})

    best = max((v2, v3), key=lambda v: (v['ok'], v['chars'], v['mean_sentence_len']))
    md = md2 if best is v2 else md3
    tier = 'generic' if best is v2 else 'fallback'
    result.update(tier=tier, validated=best['ok'], validation=best, markdown=md,
                  strategy=result.get('strategy') or ('generic' if tier == 'generic' else strategy3))
    return _finish(result, t0, store, log, sig)


def _apply_rule(html_str: str, rule: dict, profile: str) -> str:
    root = select.parse_html(html_str)
    hits = select.apply_rule(root, rule.get('include_xpaths'), rule.get('exclude_xpaths'))
    if not hits:
        return ''
    select.prune_unmarked(root)
    return serialize.render(root, profile=rule.get('profile') or profile, filter_mode=True)


def _finish(result: dict, t0: float, store: Store | None, log: bool,
            sig=None) -> dict:
    result['elapsed_ms'] = round((time.time() - t0) * 1000, 1)
    result['needs_authoring'] = not result['validated']
    if store is not None and log:
        info = result['signature']
        store.log_episode(
            url=result['url'], html_hash=result['html_hash'],
            signature_fine=info['fine'], signature_coarse=info['coarse'],
            signature_family=info.get('family', ''),
            tier=result['tier'], rule_id=result['rule_id'],
            validated=result['validated'],
            reasons=(result['validation'] or {}).get('reasons', []),
            chars=(result['validation'] or {}).get('chars', 0),
            needs_authoring=result['needs_authoring'],
            profile=result['profile'])
        if sig is not None:
            store.note_signature(info['fine'], info['coarse'], result['url'],
                                 shape_summary(sig))
    return result
