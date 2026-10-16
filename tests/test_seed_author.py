import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm import seed as S
from wmm import select

PAGE = """<html><body>
<div id=wrap><div class=sidebar><p cc-select=false>Side</p></div>
<div class=content><h2 cc-select=true>Title</h2>
<p cc-select=true>Body paragraph.</p><pre cc-select=true><code>x=1</code></pre></div></div>
</body></html>"""


def _lca(html):
    root = select.parse_html(html)
    body = root.find('.//body')
    sel = [e for e in root.iter() if isinstance(e.tag, str) and e.get('cc-select') == 'true']
    maximal = [e for e in sel if not (e.getparent() is not None
                                      and e.getparent().get('cc-select') == 'true')]
    return S.lca(maximal), body


def test_anchored_selector_uses_the_deepest_reusable_anchor():
    node, body = _lca(PAGE)
    sel, strength = S.anchored_selector(node, body)
    assert strength == 'anchored'
    assert "contains(@class,'content')" in sel


def test_selector_applies_and_selects_only_content():
    node, body = _lca(PAGE)
    sel, _ = S.anchored_selector(node, body)
    root = select.parse_html(PAGE)
    hits = select.apply_rule(root, [sel])
    assert hits >= 1
    select.prune_unmarked(root)
    text = root.text_content()
    assert 'Body paragraph.' in text
    assert 'Side' not in text            # chrome sibling excluded


def test_sanitize_rejects_positional_and_text_predicates():
    from wmm.author import sanitize_xpaths
    good = "//div[@id='content']/article/p"
    bad = ["//div[3]/p[2]", "//p[text()='x']", "//div[contains(@href,'a')]"]
    assert sanitize_xpaths([good] + bad) == [good]


def test_induce_reports_missing_key():
    sel, reason = S.induce('<html><body><p>nothing labelled</p></body></html>')
    assert sel is None and reason == 'no_key'


def test_seed_from_jsonl_promotes_validated_rules(tmp_path):
    import json
    from wmm.store import Store

    page = """<html><head><title>Seed Probe Article</title></head><body>
    <nav><a href=/>Home</a><a href=/x>About</a></nav>
    <div id=page><div class=content>
    <h2 cc-select=true>Seed Probe Article</h2>
    <p cc-select=true>""" + ('A long enough paragraph of real prose to satisfy the gate. ' * 8) + """</p>
    <p cc-select=true>""" + ('A second paragraph of prose with enough substance to count. ' * 8) + """</p>
    </div></div><footer>Copyright. All rights reserved.</footer></body></html>"""

    p = tmp_path / 'pages.jsonl'
    p.write_text(json.dumps({'html': page, 'url': 'https://probe.example/a'}) + '\n',
                encoding='utf-8')
    store = Store(tmp_path / 'db')
    try:
        tally = S.seed_from_jsonl(str(p), store, limit=1)
        assert tally['inducible'] == 1
        assert tally['validated'] == 1
        assert tally['promoted'] == 1
    finally:
        store.close()
