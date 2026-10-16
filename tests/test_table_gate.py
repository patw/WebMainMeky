import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm import select, serialize

LAYOUT = """<html><body><div class=menu><table><tr><td><a>Home</a></td><td><a>About</a></td></tr>
<tr><td><a>Shop</a></td><td><a>Contact</a></td></tr></table></div>
<article><p>""" + ('Real prose paragraph that belongs in the output. ' * 6) + """</p></article>
</body></html>"""

SCAFFOLD = """<html><body><table><tr><td><p>""" + ('First post body text with real sentences. ' * 8) + """</p></td></tr>
<tr><td><p>""" + ('Second post body text with real sentences too. ' * 8) + """</p></td></tr></table></body></html>"""

DATA = """<html><body><article><p>Context paragraph before the data table.</p>
<table><thead><tr><th>Region</th><th>Revenue</th></tr></thead>
<tbody><tr><td>North</td><td>1,200</td></tr><tr><td>South</td><td>980</td></tr></tbody></table>
</article></body></html>"""


def _md(html):
    root = select.parse_html(html)
    serialize.mark_all(root)
    return serialize.render(root, profile='canonical', filter_mode=True)


def test_menu_table_is_not_emitted_as_a_grid():
    md = _md(LAYOUT)
    assert '| Home |' not in md
    assert 'Real prose paragraph' in md


def test_page_scaffold_table_is_rendered_as_prose():
    md = _md(SCAFFOLD)
    assert '|' not in md.split('\n')[0]
    assert 'First post body text' in md and 'Second post body text' in md
    assert not any(l.startswith('|') for l in md.split('\n'))


def test_data_table_is_emitted_as_a_grid():
    md = _md(DATA)
    assert '| Region | Revenue |' in md
    assert '|---|---|' in md
    assert '| North | 1,200 |' in md
    assert 'Context paragraph' in md
