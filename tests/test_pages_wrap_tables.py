"""`_wrap_tables` boxes every rendered table, whatever attributes its open tag carries."""

from __future__ import annotations

from booth_review.build.pages import _wrap_tables


def test_a_bare_table_is_boxed() -> None:
    out = _wrap_tables("<table><tr><td>a</td></tr></table>")
    assert out == '<div class="table-scroll"><table><tr><td>a</td></tr></table></div>'


def test_a_table_with_attributes_is_boxed_in_balance() -> None:
    out = _wrap_tables('<table class="x"><tr><td>a</td></tr></table><p>after</p>')
    assert out == (
        '<div class="table-scroll"><table class="x"><tr><td>a</td></tr></table></div><p>after</p>'
    )
    assert out.count("<div") == out.count("</div>")


def test_two_tables_are_each_boxed_and_a_tablesaw_tag_is_left_alone() -> None:
    out = _wrap_tables("<table></table><table id='y'></table><tablesaw></tablesaw>")
    assert out.count('<div class="table-scroll">') == 2
    assert out.count("</div>") == 2
