import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from wmm import serialize, select
from wmm import validate as gate
from wmm.signature import candidate_keys, compute_signature
from wmm.store import Store

ARTICLE = """<html><head><title>How to Bake Bread at Home</title></head><body>
<nav><a href=/>Home</a> <a href=/r>Recipes</a> <a href=/a>About</a></nav>
<header><h1>Site Title</h1><form><input name=q></form></header>
<article class=post-body>
<h2>How to Bake Bread at Home</h2>
<p>Bread is one of those things that seems difficult until you try it once at home
with flour, water, salt and a warm place to let it rise. The process is forgiving.</p>
<p>Mix the flour with water and let it rest for half an hour before adding salt and
yeast. This short rest is called autolyse and it makes the dough much easier to work.</p>
<p>Shape the dough, let it proof until it is airy, then bake it in a hot oven with
steam for the first ten minutes. The steam is what gives you a glossy, crackly crust.</p>
<pre><code>oven = 250\ndough = shape(flour, water, salt, yeast)\nbake(dough, oven, steam=10)</code></pre>
<ul><li>Keep the dough warm.</li><li>Do not skip the steam.</li></ul>
</article>
<aside><a href=/ads>Ad one</a> <a href=/ads2>Ad two</a></aside>
<footer><p>All rights reserved. Privacy policy. Terms of use. Cookie policy.</p></footer>
</body></html>"""

NAV_ONLY = """<html><body><nav><a href=/>Home</a><a href=/a>About</a></nav>
<div class=menu><ul><li><a>One</a></li><li><a>Two</a></li><li><a>Three</a></li></ul></div>
<footer>Copyright. All rights reserved. Privacy policy. Terms of use.</footer></body></html>"""


def test_validate_positive_article():
    md = ("# How to Bake Bread\n\n" + "Bread is one of those things that seems difficult "
          "until you try it once at home with flour, water, salt and a warm place. " * 6
          + "\n\nMix the flour with water and let it rest for half an hour before adding "
          "salt and yeast, which makes the dough far easier to work with later.\n")
    v = gate.validate(md)
    assert v['ok'] is True, v['reasons']


def test_validate_negative_nav_only():
    nav_text = ('Home  Recipes  About  Sign in  Subscribe  Search the site  '
                'Copyright. All rights reserved. Privacy policy. Terms of use. '
                'Cookie policy. Add to cart. Shopping cart. Sitemap.')
    v = gate.validate(nav_text)
    assert v['ok'] is False
    assert any('too_short' in r for r in v['reasons'])


def test_validate_negative_link_farm():
    md = ' '.join(f'[A long descriptive link text number {i} pointing at a page](/x/{i})'
                  for i in range(80))
    v = gate.validate(md)
    assert v['ok'] is False
    assert any('link_density' in r for r in v['reasons'])


def test_serializer_shapes():
    root = select.parse_html(ARTICLE)
    select.select_generic(root, ARTICLE)
    select.prune_unmarked(root)
    md = serialize.render(root, profile='canonical', filter_mode=True)
    assert '## How to Bake Bread at Home' in md
    assert '```' in md and 'bake(dough, oven, steam=10)' in md
    assert '- Keep the dough warm.' in md
    assert 'All rights reserved' not in md          # footer suppressed
    assert 'Ad one' not in md                        # aside suppressed


def test_profile_link_difference():
    root = select.parse_html('<html><body><article><p>' +
                             ('Some sufficiently long prose about baking bread. ' * 12) +
                             '<a href=/x>Reference link</a></p></article></body></html>')
    serialize.mark_all(root)
    canon = serialize.render(root, profile='canonical', filter_mode=True)
    gt = serialize.render(root, profile='gt', filter_mode=True)
    assert '[Reference link](/x)' in canon
    assert '[Reference link]' not in gt


def test_signature_family_groups_layouts():
    a = compute_signature(select.parse_html(ARTICLE))
    b = compute_signature(select.parse_html(ARTICLE.replace('Bread is one of those',
                                                            'Dough is one of those')))
    assert a.family == b.family          # same layout, different words
    c = compute_signature(select.parse_html(NAV_ONLY))
    assert c.family != a.family          # different layout


def test_rule_lifecycle_and_provenance(tmp_path):
    store = Store(tmp_path)
    try:
        r = store.upsert_rule(signature='sigA', level='family',
                              include_xpaths=["//article"], provenance='llm')
        assert r['status'] == 'candidate'
        r = store.record_outcome(r['_id'], True)
        assert r['status'] == 'candidate'          # LLM rules need two successes
        r = store.record_outcome(r['_id'], True)
        assert r['status'] == 'active'

        r2 = store.upsert_rule(signature='sigA', level='family',
                               include_xpaths=["//main"], provenance='induced')
        r2 = store.record_outcome(r2['_id'], True)
        assert r2['status'] == 'active'            # induced rules promote on one

        assert store.find_rule(['sigA']) is not None
        store.set_rule_status(r['_id'], 'retired')
        store.set_rule_status(r2['_id'], 'retired')
        assert store.find_rule(['sigA']) is None   # retired rules are never used
    finally:
        store.close()


def test_pipeline_generic_tier(tmp_path):
    from wmm.pipeline import extract
    store = Store(tmp_path)
    try:
        res = extract(ARTICLE, url='https://example.com/bread', store=store, log=True)
        assert res['tier'] in ('generic', 'rule')
        assert res['validated'] is True
        assert 'Bread is one of those' in res['markdown']
        assert store.episodes.count({}) == 1
        assert store.episodes.find({'needs_authoring': False}).count() == 1
    finally:
        store.close()


def test_pipeline_rule_tier(tmp_path):
    from wmm.pipeline import extract
    store = Store(tmp_path)
    try:
        sig = compute_signature(select.parse_html(ARTICLE))
        key = sig.family
        rule = store.upsert_rule(signature=key, level='family',
                                 include_xpaths=['//article'], provenance='human',
                                 flags=sig.flags)
        store.set_rule_status(rule['_id'], 'active')
        store.rules.update_one({'_id': rule['_id']}, set={'confidence': 0.9})
        res = extract(ARTICLE, url='https://example.com/bread', store=store, log=False)
        assert res['tier'] == 'rule', res['attempts']
        assert res['validated'] is True
    finally:
        store.close()


def test_pipeline_fallback_on_chrome_only(tmp_path):
    from wmm.pipeline import extract
    store = Store(tmp_path)
    try:
        res = extract(NAV_ONLY, url='https://example.com/nav', store=store, log=True)
        assert res['validated'] is False
        assert res['needs_authoring'] is True      # this is what feeds the author loop
    finally:
        store.close()
