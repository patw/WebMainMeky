import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm import golden as G
from wmm import select, serialize, trim
from wmm.store import Store

ARTICLE_TAIL = """<html><body><main>
<h1>Golden Article</h1>
<p>""" + ('A real paragraph of article prose with sentences that end in periods. ' * 6) + """</p>
<h2>Related Posts</h2>
<ul><li><a href=/a>Old post one</a></li><li><a href=/b>Old post two</a></li>
<li><a href=/c>Old post three</a></li></ul>
<h2>Leave a Reply</h2>
<p>Comments are closed for this article, please check back later for updates.</p>
</main></body></html>"""


def test_stop_heading_truncates_after_the_article():
    root = select.parse_html(ARTICLE_TAIL)
    serialize.mark_all(root)
    md = serialize.render(root, profile='canonical', filter_mode=True)
    assert 'A real paragraph of article prose' in md
    assert 'Old post one' not in md
    assert 'Comments are closed' not in md


def test_stop_heading_does_not_fire_on_a_short_page():
    prose = 'Enough prose to pass the minimum length guard for stopping. ' * 12
    short = ('<html><body><main><p>Short note.</p><h2>Related Posts</h2><p>'
             + prose + '</p></main></body></html>')
    root = select.parse_html(short)
    serialize.mark_all(root)
    md = serialize.render(root, profile='canonical', filter_mode=True)
    assert 'Enough prose to pass' in md


def test_link_list_block_is_dropped():
    block = "- [Alpha page](/a)\n- [Beta page](/b)\n- [Gamma page](/c)\n- [Delta page](/d)"
    assert trim.is_link_list(block)
    assert trim.trim_blocks([block]) == []


def test_low_value_block_is_dropped_but_prose_kept():
    assert trim.is_low_value('Home  About  Contact  Search')
    assert not trim.is_low_value('This paragraph makes a claim and ends with a period.')


def test_golden_gate_blocks_a_rule_that_mangles_a_golden_page(tmp_path):
    store = Store(tmp_path / 'db')
    try:
        pages = [{'url': 'https://x.test/1', 'html': ARTICLE_TAIL,
                  'markdown': 'A real paragraph of article prose with sentences that end in periods. ' * 6,
                  'domain': 'x.test', 'level': 'simple'}]
        G.store_golden(store, pages)
        from wmm.signature import compute_signature
        sig = compute_signature(select.parse_html(ARTICLE_TAIL))
        # a selector that grabs the recommendation list instead of the article:
        # it matches the golden layout and produces nothing usable
        rule = store.upsert_rule(signature=sig.family, level='family',
                                 include_xpaths=['//ul'], provenance='llm',
                                 profile='gt')
        rule = store.record_outcome(rule['_id'], True)
        rule = store.record_outcome(rule['_id'], True)
        assert rule['status'] == 'candidate', rule
        assert rule['golden_checked'] >= 1
        assert rule['golden_mean'] is not None and rule['golden_mean'] < 0.55
    finally:
        store.close()


def test_golden_gate_allows_a_clean_rule(tmp_path):
    store = Store(tmp_path / 'db')
    try:
        G.store_golden(store, [{'url': 'https://x.test/1', 'html': ARTICLE_TAIL,
                                'markdown': 'A real paragraph of article prose with sentences that end in periods. ' * 6,
                                'domain': 'x.test', 'level': 'simple'}])
        from wmm.signature import compute_signature
        sig = compute_signature(select.parse_html(ARTICLE_TAIL))
        rule = store.upsert_rule(signature=sig.family, level='family',
                                 include_xpaths=['//main'], provenance='llm',
                                 profile='gt')
        rule = store.record_outcome(rule['_id'], True)
        rule = store.record_outcome(rule['_id'], True)
        assert rule['status'] == 'active', rule
        assert rule['golden_mean'] >= 0.55
    finally:
        store.close()
