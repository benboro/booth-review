"""WR-09: the opt-in real-data browser test must never let pytest's
assertion introspection print vault records.

On a failed `assert`, pytest prints the repr of every sub-expression it
can see (`where 3 = len([{'id': ..., 'name': ...}, ...])`), and a custom
message does not stop that. So every `assert` in
`tests/e2e/test_site_realdata.py` may only compare plain local names and
constants -- anything computed from real data (a `len(...)`, an attribute
like `page.url`, a subscript) has to be bound to a local on an earlier line.
This reads the file's AST only; it never touches the vault.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REALDATA_TEST = Path(__file__).resolve().parent / "e2e" / "test_site_realdata.py"

_ALLOWED = (ast.Name, ast.Constant, ast.Compare, ast.UnaryOp, ast.BoolOp, ast.cmpop, ast.unaryop)
_ALLOWED_CONTEXT = (ast.Load, ast.boolop)


def _plain(node: ast.AST) -> bool:
    return all(isinstance(sub, _ALLOWED + _ALLOWED_CONTEXT) for sub in ast.walk(node))


def test_realdata_asserts_compare_only_plain_locals() -> None:
    tree = ast.parse(_REALDATA_TEST.read_text(encoding="utf-8"))
    asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    assert asserts, "expected the real-data test to contain assertions"
    offending = [node.lineno for node in asserts if not _plain(node.test)]
    assert offending == [], f"asserts that could print vault data, at lines {offending}"


def test_hygiene_check_rejects_an_inline_len() -> None:
    """The checker itself flags the exact pattern WR-09 reported."""
    node = ast.parse("assert len(expected) == len(people)").body[0]
    assert isinstance(node, ast.Assert)
    assert not _plain(node.test)
    ok = ast.parse("assert n_expected == n_people").body[0]
    assert isinstance(ok, ast.Assert)
    assert _plain(ok.test)


def test_every_guard_install_is_asserted() -> None:
    """F12: a function that installs the off-origin guard must also assert it is clean; a
    discarded `_install_guard` result would let an off-origin request pass unnoticed."""
    tree = ast.parse(_REALDATA_TEST.read_text(encoding="utf-8"))
    unasserted = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        called = {
            node.func.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if "_install_guard" in called and "_assert_guard_clean" not in called:
            unasserted.append(fn.name)
    assert unasserted == [], f"guards installed but never asserted in {unasserted}"
