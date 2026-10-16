import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wmm import select, serialize
from wmm.mathfmt import escape_dollars, looks_math

GRID = """<html><body><article><p>Intro paragraph with enough words to be a paragraph.</p>
<table>
 <thead><tr><th>Item</th><th colspan=2>Price</th></tr></thead>
 <tbody>
  <tr><td rowspan=2>Bread</td><td>white</td><td>3.00</td></tr>
  <tr><td>rye</td><td>4.00</td></tr>
  <tr><td>Cake</td><td>plain</td><td>5.00</td></tr>
 </tbody>
</table></article></body></html>"""


def test_colspan_and_rowspan_expand_into_a_rectangular_grid():
    root = select.parse_html(GRID)
    serialize.mark_all(root)
    md = serialize.render(root, profile='canonical', filter_mode=True)
    lines = [l for l in md.split('\n') if l.startswith('|')]
    header = lines[0]
    assert header.count('|') == 4                     # 3 columns
    assert '---|' in lines[1]
    body = lines[2:]
    for row in body:
        assert row.count('|') == 4, row               # rowspan filled, no ragged rows
    joined = '\n'.join(body)
    assert 'Bread' in joined and 'rye' in joined and 'Cake' in joined


def test_header_row_detected_from_th():
    root = select.parse_html(GRID)
    serialize.mark_all(root)
    md = serialize.render(root, profile='canonical', filter_mode=True)
    lines = [l for l in md.split('\n') if l.startswith('|')]
    assert 'Item' in lines[0] and 'Price' in lines[0]
    assert 'white' not in lines[0]


def test_math_escaping_keeps_currency_escaped():
    md = 'It costs \\$25.99 today and the formula \\$x^2 + y^2 = r^2\\$ is exact.'
    out = escape_dollars(md)
    assert '\\$25.99' in out                          # currency stays escaped
    assert '$x^2 + y^2 = r^2$' in out                 # formula becomes real math
    assert looks_math('x^2 + y^2 = r^2') is True
    assert looks_math('1,150.00') is False


def test_math_escaping_is_idempotent_on_plain_text():
    md = 'No money and no math here, just prose about bread and flour.'
    assert escape_dollars(md) == md
