"""Güvenli hesap makinesi (AST tabanlı) testleri."""

from __future__ import annotations

import pytest

from nova.tools import ToolError, format_number, safe_calculate


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2+2", 4.0),
        ("25*4", 100.0),
        ("(25*4)/2", 50.0),
        ("sqrt(81)", 9.0),
        ("2^10", 1024.0),
        ("-3 + 1", -2.0),
        ("10 % 3", 1.0),
        ("round(2.567, 2)", 2.57),
        ("max(3, 8, 5)", 8.0),
        ("pi", 3.141592653589793),
        ("2,5 * 4", 10.0),
    ],
)
def test_safe_calculate_valid(expression, expected):
    assert safe_calculate(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "1+1; 2",
        """'a' * 3""",
        "[1,2,3]",
        "2 ** 999999",
        "9 ** 100000",
        "1/0",
        "",
        "(1+2",
    ],
)
def test_safe_calculate_rejects_dangerous_input(expression):
    with pytest.raises(ToolError):
        safe_calculate(expression)


def test_format_number_uses_turkish_decimal_separator():
    assert format_number(100.0) == "100"
    assert format_number(2.5) == "2,5"
    assert format_number(-0.25) == "-0,25"
