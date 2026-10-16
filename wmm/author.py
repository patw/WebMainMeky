"""Rule authoring: the ONLY place an LLM touches this system, and it runs off the
hot path (background job / CLI), never inside /extract.

Flow: a failed episode -> compact page skeleton -> ask for include/exclude XPaths
-> verify mechanically on the page -> store as a CANDIDATE rule. Promotion to
'active' happens in the store, only after MIN_SUPPORT successful re-validations.
"""
from __future__ import annotations

import json
import re

from openai import OpenAI

from . import config, pipeline, select, serialize, validate as gate
from .signature import candidate_keys, compute_signature
from .store import Store

SYSTEM = (
    "You are a web main-content extraction rule author. You receive a page's block "
    "skeleton (depth, tag, semantic class tokens, text preview) and the text that a "
    "generic extractor produced, which was judged wrong. Propose XPath selectors that "
    "select the elements containing the real main content, and selectors for chrome to "
    "suppress.\n"
    "Rules for your answer:\n"
    "- Return ONLY JSON: {\"include_xpaths\": [...], \"exclude_xpaths\": [...], "
    "\"notes\": \"...\"}\n"
    "- XPaths must be structural and reusable: prefer //div[@id='content'], "
    "//article, //section[@class='post-body']. Use tag steps and @id/@class predicates.\n"
    "- NEVER use positional indexes like div[3]/p[7]. NEVER use text() predicates. "
    "NEVER use generated class names that contain hex runs or long digit runs.\n"
    "- Include the fewest selectors that cover the article body. Do not include the "
    "whole page.\n"
    "- If the page has no recoverable main content, return empty lists."
)

SKELETON_CAP = 220


def build_skeleton(html_str: str) -> str:
    """Compact, model-friendly view of the page: block shape + text previews."""
    from .dom import block_elements, hidden, semantic_tokens, text_len
    root = select.parse_html(html_str)
    body = root.find('.//body')
    if body is None:
        return ''
    lines = []
    for el, depth in block_elements(body):
        if hidden(el) or len(lines) >= SKELETON_CAP:
            continue
        toks = ' '.join(sorted(semantic_tokens(el))[:3])
        tl = text_len(el)
        preview = re.sub(r'\s+', ' ', el.text_content()).strip()[:90]
        lines.append(f"{depth:>2} {el.tag:<9} {tl:>6} {'[' + toks + ']' if toks else '':<28} {preview}")
    return '\n'.join(lines)


def _user_prompt(url: str, skeleton: str, failed: str, reasons: list[str]) -> str:
    return (
        f"URL: {url}\n"
        f"Validation failures: {', '.join(reasons) if reasons else 'unknown'}\n\n"
        f"PAGE SKELETON (depth tag textlen [class/id] preview):\n{skeleton}\n\n"
        f"WHAT THE GENERIC EXTRACTOR PRODUCED (first 1200 chars):\n{(failed or '')[:1200]}\n\n"
        "Return the JSON rule now."
    )


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    fence = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start == -1 or end == -1:
            return None
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except Exception:
        return None


_BAD_XPATH = re.compile(r'\[\d+\]|text\(\)|\bcontains\(|\bnot\(', re.I)


def sanitize_xpaths(exprs, max_n: int = 8) -> list[str]:
    """Reject selectors that cannot generalize (positional, text-matching)."""
    out = []
    for e in exprs or []:
        e = (e or '').strip()
        if not e.startswith('/'):
            continue
        if _BAD_XPATH.search(e):
            continue
        if len(e) > 400:
            continue
        out.append(e)
        if len(out) >= max_n:
            break
    return out


def author_rule(store: Store, episode: dict, html_str: str,
                profile: str = 'canonical') -> dict:
    """Ask the model for a rule, verify it mechanically, store as candidate."""
    sig = compute_signature(select.parse_html(html_str))
    keys = candidate_keys(sig)
    if not keys:
        return {'ok': False, 'reason': 'page too small for a signature'}

    skeleton = build_skeleton(html_str)
    if not skeleton:
        return {'ok': False, 'reason': 'no body to describe'}

    client = OpenAI(base_url=config.OPENAI_BASE_URL, api_key=config.OPENAI_API_KEY,
                    timeout=config.OPENAI_TIMEOUT)
    try:
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{'role': 'system', 'content': SYSTEM},
                      {'role': 'user',
                       'content': _user_prompt(episode.get('url', ''), skeleton,
                                               episode.get('markdown_preview', ''),
                                               episode.get('reasons', []) or [])}],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
    except Exception as exc:
        return {'ok': False, 'reason': f'llm_error:{type(exc).__name__}:{exc}'}

    parsed = _parse_json(raw)
    if not parsed:
        return {'ok': False, 'reason': 'unparseable_model_output', 'raw': (raw or '')[:400]}

    include = sanitize_xpaths(parsed.get('include_xpaths'))
    exclude = sanitize_xpaths(parsed.get('exclude_xpaths'))
    if not include:
        return {'ok': False, 'reason': 'no_usable_selectors', 'raw': (raw or '')[:400]}

    # mechanical verification: the rule must actually produce valid output on this page
    root = select.parse_html(html_str)
    hits = select.apply_rule(root, include, exclude)
    if not hits:
        return {'ok': False, 'reason': 'selectors_matched_nothing',
                'include': include, 'exclude': exclude}
    select.prune_unmarked(root)
    md = serialize.render(root, profile=parsed.get('profile') or profile, filter_mode=True)
    v = gate.validate(md)

    key = keys[0]
    rule = store.upsert_rule(signature=key, level='fine' if sig.fine else 'coarse',
                             include_xpaths=include, exclude_xpaths=exclude,
                             provenance='llm', profile=profile,
                             url=episode.get('url', ''),
                             notes=(parsed.get('notes') or '')[:400])
    rule = store.record_outcome(rule['_id'], v['ok'])

    return {'ok': True, 'validated': v['ok'], 'validation': v, 'rule': rule,
            'include': include, 'exclude': exclude, 'signature': key,
            'markdown_chars': len(md)}
