"""Parser tests on hand-made inputs (no PDFs needed)."""

from datetime import date
from types import SimpleNamespace as NS

from telecom import parse as P


def test_numbers_and_names_survive_pdf_spacing():
    assert P.number("1 0,096,942") == 10096942
    assert P.number("(5,879)") == -5879
    assert P.number("-") is None and P.number("") is None
    assert P.lsa_name("W est Bengal") == "West Bengal"
    assert P.lsa_name("U.P. (W )") == "U.P. (West)" and P.lsa_name("UP (East)") == "U.P. (East)"
    assert P.lsa_name("Jammu and Kashmir") == "Jammu & Kashmir" and P.lsa_name("Total") is None


def test_month_from_text_and_title():
    assert P.report_month("Highlights of Telecom Subscription Data at the end of August 2026") == date(2026, 8, 1)
    assert P.month_from_title("Telecom Subscription Data as on 31st, October, 2025") == date(2025, 10, 1)
    assert P.month_from_title("Telecom Subscription Data as on February 2026") == date(2026, 2, 1)


def test_glued_month_headers_are_split():
    row = [P.Token("Jul-25", 100, 120), P.Token("July-25August-25", 200, 360), P.Token("Total", 400, 420)]
    xs = P._month_anchors(row)
    assert len(xs) == 3 and xs[1] < 280 < xs[2]


def _char(text, x, top):
    return {"text": text, "x0": x, "x1": x + 5, "top": top}


def test_rows_from_chars_groups_slightly_offset_rows():
    page = NS(chars=[_char(c, 10 + 5 * i, 100.0) for i, c in enumerate("Assam")]
               + [_char(c, 100 + 5 * i, 102.6) for i, c in enumerate("1,234")]
               + [_char(c, 10 + 5 * i, 120.0) for i, c in enumerate("Bihar")])
    rows = P.rows_from_chars(page)
    assert [P.row_text(r) for r in rows] == ["Assam 1,234", "Bihar"]


def test_m2m_from_text():
    text = ("The Number of M2M cellular mobile connections increased from 118.47 million at the end of "
            "February 2026 to 123.88 million at the end of March 2026. Bharti Airtel Limited has the highest "
            "number of M2M cellular mobile connections of 76.99 million with a market share of 62.15%, followed "
            "by Reliance Jio Infocomm Limited, Vodafone Idea Limited and BSNL with market share of 18.76%, "
            "15.81% and 3.28% respectively.")
    rows = {r["operator"]: r["m2m"] for r in P.m2m_from_text(text, date(2026, 3, 1))}
    assert rows["Airtel"] == 76.99e6
    assert round(rows["Jio"] / 1e6, 2) == round(123.88 * 0.1876, 2)
    assert set(rows) == {"Airtel", "Jio", "Vi", "BSNL"}
