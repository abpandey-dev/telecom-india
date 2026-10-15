"""Extract operator x circle tables from TRAI's monthly "Telecom Subscription Data" press releases.

  mobile   Annexure II: wireless (mobile) subscribers per operator per Licensed Service Area ("circle"),
           for the report month and the previous month (so a month whose own report can't be read is
           recovered from the next one)
  active   Annexure III: VLR as % of HLR, the share of an operator's SIMs active on the peak day
  rural    the "Rural Subscribers" row of Annexure II (national, per operator)

TRAI's PDFs come in several layouts over the years: ruled tables, tables without grid lines, and landscape
tables whose characters are flagged as rotated. Instead of relying on table detection, this module rebuilds
rows from character positions and assigns every number to the nearest column anchor (the month headers or
operator names), so blank cells can't shift columns. Every month is then checked: the circles must add up to
TRAI's own "Total" row for every operator, or the month is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import pdfplumber

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], start=1)}
MON3 = {k[:3]: v for k, v in MONTHS.items()} | {"sept": 9, "july": 7, "june": 6}

LSAS = ["Andhra Pradesh", "Assam", "Bihar", "Delhi", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu & Kashmir",
        "Karnataka", "Kerala", "Kolkata", "Madhya Pradesh", "Maharashtra", "Mumbai", "North East", "Odisha",
        "Punjab", "Rajasthan", "Tamil Nadu", "U.P. (East)", "U.P. (West)", "West Bengal"]
_LSA_KEYS = {re.sub(r"[^a-z]", "", n.lower()): n for n in LSAS}
_LSA_KEYS |= {"upe": "U.P. (East)", "upw": "U.P. (West)", "upeast": "U.P. (East)", "upwest": "U.P. (West)",
              "jammuandkashmir": "Jammu & Kashmir", "jk": "Jammu & Kashmir", "orissa": "Odisha",
              "tamilnaduincludingchennai": "Tamil Nadu", "tamilnaduinclchennai": "Tamil Nadu"}

# (pattern on squashed header text, canonical name); order matters: "reliancejio" before "reliance"
OPERATOR_PATTERNS = [("bhartiairtel", "Airtel"), ("bharti", "Airtel"), ("airtel", "Airtel"),
                     ("reliancejio", "Jio"), ("jio", "Jio"), ("reliancecom", "RCom"), ("vodafoneidea", "Vi"),
                     ("vodafone", "Vi"), ("bsnl", "BSNL"), ("mtnl", "MTNL"), ("total", "Total")]


def squash(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def lsa_name(text) -> str | None:
    return _LSA_KEYS.get(re.sub(r"[^a-z]", "", str(text or "").lower()))


def number(tok) -> float | None:
    """'1,096,942' -> 1096942; '(5,879)' -> -5879; '-' -> None."""
    s = squash(tok).replace(",", "")
    if s in ("", "-", "--", "na"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()"))
    except ValueError:
        return None
    return -v if neg else v


def report_month(text: str) -> date:
    t = " ".join(text.split())
    for m in re.finditer(r"(?:at the end of|as on)\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?([A-Za-z]+),?\s+(\d{4})", t, re.I):
        if m.group(1).lower() in MONTHS:
            return date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
    raise ValueError("report month not found")


# --- rebuilding rows from characters ----------------------------------------------------------------

@dataclass
class Token:
    text: str
    x0: float
    x1: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


def rows_from_chars(page, y_tol: float = 4.0, gap: float = 2.0) -> list[list[Token]]:
    """Group characters into rows by vertical position, then split each row into tokens at horizontal gaps."""
    chars = sorted((c for c in page.chars if c["text"].strip()), key=lambda c: (round(c["top"]), c["x0"]))
    rows: list[list[dict]] = []
    for c in chars:
        for r in rows[-6:]:
            if abs(r[0]["top"] - c["top"]) <= y_tol:
                r.append(c)
                break
        else:
            rows.append([c])
    out = []
    for r in sorted(rows, key=lambda r: r[0]["top"]):
        r.sort(key=lambda c: c["x0"])
        toks, cur = [], [r[0]]
        for c in r[1:]:
            if c["x0"] - cur[-1]["x1"] > gap:
                toks.append(cur)
                cur = [c]
            else:
                cur.append(c)
        toks.append(cur)
        out.append([Token("".join(ch["text"] for ch in t), t[0]["x0"], t[-1]["x1"]) for t in toks])
    return out


def row_text(row: list[Token]) -> str:
    return " ".join(t.text for t in row)


def _label_and_numbers(row: list[Token]) -> tuple[str, list[Token]]:
    """Leading non-numeric tokens form the label; the rest are cells."""
    label, cells = [], []
    for t in row:
        if not cells and number(t.text) is None and t.text.strip() not in ("-", "--"):
            label.append(t.text)
        else:
            cells.append(t)
    return " ".join(label), cells


def _nearest(anchors: list[float], x: float, tol: float) -> int | None:
    i = min(range(len(anchors)), key=lambda k: abs(anchors[k] - x))
    return i if abs(anchors[i] - x) <= tol else None


def _operator_positions(rows: list[list[Token]], before: int) -> list[tuple[float, str]]:
    """Find operator names in the header rows above `before`: returns (x-centre, operator) left to right.

    Uses the fewest tokens that spell a name ("Bharti", "Reliance Jio"), so the centre isn't pulled sideways.
    """
    found = []
    for row in rows[max(0, before - 6):before + 1]:
        i = 0
        while i < len(row):
            hit = None
            for j in (1, 2, 3):
                chunk = row[i:i + j]
                if len(chunk) < j:
                    break
                key = squash("".join(t.text for t in chunk))
                if key.startswith("bsnl(vno") or (key == "bsnl" and i + 1 < len(row)
                                                  and squash(row[i + 1].text).startswith("(vno")):
                    hit = (j if key.startswith("bsnl(vno") else j + 1, "BSNL VNO")
                    break
                op = next((name for pat, name in OPERATOR_PATTERNS if key.startswith(pat)), None)
                if op:
                    hit = (j, op)
                    break
            if hit:
                j, op = hit
                chunk = row[i:i + j]
                found.append(((chunk[0].x0 + chunk[-1].x1) / 2, op))
                i += j
            else:
                i += 1
    best = {}
    for x, op in found:
        best.setdefault(op, x)
    return sorted(((x, op) for op, x in best.items()), key=lambda t: t[0])


MONTH_TOKEN = re.compile(r"[A-Za-z]{3,9}-\d{2}")


def _month_anchors(row: list[Token]) -> list[float]:
    """x-centres of month headers; splits glued tokens such as 'July-25August-25' by character position."""
    out = []
    for t in row:
        hits = list(MONTH_TOKEN.finditer(t.text))
        if not hits or "".join(h.group(0) for h in hits) != t.text:
            continue
        w = (t.x1 - t.x0) / len(t.text)
        out += [t.x0 + w * (h.start() + h.end()) / 2 for h in hits]
    return out


# Reliance Communications has a few hundred legacy subscribers whose tiny cells don't align reliably; it is not
# part of this analysis. BSNL's virtual network operators (listed separately in 2024) are counted under BSNL.
SKIP_OPERATORS = {"RCom", "Total"}


def parse_mobile(page, month: date) -> tuple[list[dict], list[dict]]:
    rows = rows_from_chars(page)
    mrow = next(i for i, r in enumerate(rows) if len(_month_anchors(r)) >= 6)
    anchors = _month_anchors(rows[mrow])
    ops = _operator_positions(rows, mrow)
    # pair consecutive month anchors (previous, current) and name each pair by the nearest operator header
    pairs = [(anchors[k], anchors[k + 1]) for k in range(0, len(anchors) - 1, 2)]
    col_op = {}
    for k, (a, b) in enumerate(pairs):
        mid = (a + b) / 2
        x, op = min(ops, key=lambda o: abs(o[0] - mid))
        col_op[2 * k], col_op[2 * k + 1] = (op, "prev"), (op, "cur")
    spacing = min(b - a for a, b in zip(anchors, anchors[1:])) if len(anchors) > 1 else 50
    prev_month = date(month.year - (month.month == 1), 12 if month.month == 1 else month.month - 1, 1)
    out, rural, totals = [], [], {}
    for r in rows[mrow + 1:]:
        label, cells = _label_and_numbers(r)
        name, key = lsa_name(label), squash(label)
        if not (name or key.startswith("total") or key.startswith("rural")):
            continue
        vals = {}
        for t in cells:
            k = _nearest(anchors, t.xc, spacing * 0.6)
            if k is not None and k in col_op:
                vals[col_op[k]] = number(t.text)
        for (op, which), v in vals.items():
            if op in SKIP_OPERATORS or v is None:
                continue
            when = month if which == "cur" else prev_month
            if name:
                out.append({"month": when, "lsa": name, "operator": op, "subscribers": v, "source": which})
            elif key.startswith("rural") and which == "cur":
                rural.append({"month": month, "operator": op, "rural_subscribers": v})
            elif key.startswith("total"):
                totals[(op, which)] = v
    # Self-check against TRAI's own Total row. The two months in the table are verified separately: a month that
    # fails is dropped (with the reason), the other is kept, e.g. when one column uses an unreadable font.
    if not totals:
        raise ValueError(f"{month:%Y-%m}: no Total row found, can't verify")
    failed = {}
    for (op, which), t in totals.items():
        if op in SKIP_OPERATORS or t is None:
            continue
        when = month if which == "cur" else prev_month
        got = sum(x["subscribers"] for x in out if x["operator"] == op and x["month"] == when)
        if abs(got - t) > 1:
            failed[(op, which)] = f"{when:%Y-%m} {op}: circles add up to {got:,.0f} but TRAI's Total says {t:,.0f}"
    # Each operator-month is verified on its own, so a bad column (unreadable font, misaligned tiny cells) only
    # removes that operator for that month. Operators without a Total cell can't be verified and are dropped too.
    verified = {k for k in totals if k not in failed and k[0] not in SKIP_OPERATORS and totals[k] is not None}
    out = [x for x in out if (x["operator"], x["source"]) in verified]
    rural = [r for r in rural if (r["operator"], "cur") in verified]
    if not out:
        raise ValueError("; ".join(failed.values()) or "nothing verified")
    folded: dict = {}
    for x in out:
        op = "BSNL" if x["operator"] == "BSNL VNO" else x["operator"]
        k = (x["month"], x["lsa"], op, x["source"])
        folded[k] = folded.get(k, 0) + x["subscribers"]
    out = [{"month": m, "lsa": l, "operator": o, "subscribers": v, "source": src} for (m, l, o, src), v in folded.items()]
    rural = [{**r, "operator": "BSNL" if r["operator"] == "BSNL VNO" else r["operator"]} for r in rural]
    return out, rural


def parse_active(page, month: date) -> list[dict]:
    rows = rows_from_chars(page)
    hrow = next(i for i, r in enumerate(rows) if squash(row_text(r)).startswith("circle"))
    ops = [(x, op) for x, op in _operator_positions(rows, hrow) if op != "Total"]
    xs = [x for x, _ in ops]
    spacing = min(b - a for a, b in zip(xs, xs[1:])) if len(xs) > 1 else 60
    out = []
    for r in rows[hrow + 1:]:
        label, cells = _label_and_numbers(r)
        name = lsa_name(label)
        if not name:
            continue
        for t in cells:
            k = _nearest(xs, t.xc, spacing * 0.6)
            v = number(t.text)
            if k is not None and v is not None:
                out.append({"month": month, "lsa": name, "operator": ops[k][1], "active_pct": v})
    return out


def _candidates(pdf, *needles: str, exclude: tuple[str, ...] = ()):
    for p in pdf.pages:
        # rebuilt rows read landscape pages correctly, where extract_text() returns one letter per line
        flat = squash(" ".join(row_text(r) for r in rows_from_chars(p)))
        if all(squash(n) in flat for n in needles) and not any(squash(x) in flat for x in exclude):
            yield p


# Annexure II is the mobile table; FWA (5G / UBR) and wireline annexures have the same shape and must be skipped.
NOT_MOBILE = ("Fixed-Wireless", "Fixed Wireless", "FWA", "UBR", "Wireline Subscriber Base", "5G-Fixed")


def _first_success(pages, fn, month):
    """Try each candidate page; return the first that parses (and passes its self-check)."""
    errors = []
    for p in pages:
        try:
            result = fn(p, month)
            if result and (result[0] if isinstance(result, tuple) else result):
                return result
        except (ValueError, StopIteration) as e:
            errors.append(f"p{p.page_number}: {e or type(e).__name__}")
    raise ValueError("; ".join(errors) or "no candidate page")


def _title_month(path: Path) -> date | None:
    import json
    idx = Path(path).parent / "report_index.json"
    if idx.exists():
        titles = {r["url"].rsplit("/", 1)[1]: r["title"] for r in json.load(open(idx))}
        return month_from_title(titles.get(Path(path).name, ""))
    return None


def parse_report(path: str | Path) -> dict:
    with pdfplumber.open(path) as pdf:
        month = _title_month(Path(path)) or report_month(" ".join((p.extract_text() or "") for p in pdf.pages[:2]))
        mobile, rural = _first_success(_candidates(pdf, "Annexure", "Wireless", "Subscriber", exclude=NOT_MOBILE),
                                       parse_mobile, month)
        try:
            active = _first_success(_candidates(pdf, "Proportion of VLR"), parse_active, month)
        except ValueError:
            active = []
    return {"month": month, "mobile": mobile, "rural": rural, "active": active}


def build(raw: str | Path = "data/raw") -> dict[str, pd.DataFrame]:
    mobile, rural, active, log = [], [], [], []
    for f in sorted(Path(raw).glob("*.pdf")):
        try:
            r = parse_report(f)
            log.append({"file": f.name, "month": r["month"], "mobile_rows": len(r["mobile"]),
                        "active_rows": len(r["active"]), "error": None})
        except (ValueError, StopIteration) as e:
            log.append({"file": f.name, "month": None, "mobile_rows": 0, "active_rows": 0,
                        "error": (str(e) or type(e).__name__)[:160]})
            continue
        mobile += r["mobile"]
        rural += r["rural"]
        active += r["active"]
    m = pd.DataFrame(mobile)
    if not m.empty:
        m["month"] = pd.to_datetime(m["month"])
        # prefer a month's own report ("cur") over the next report's "previous month" column
        m = m.sort_values("source").drop_duplicates(["month", "lsa", "operator"], keep="first")
    t = {"mobile": m, "rural": pd.DataFrame(rural), "active": pd.DataFrame(active), "log": pd.DataFrame(log)}
    for k in ("rural", "active"):
        if not t[k].empty:
            t[k]["month"] = pd.to_datetime(t[k]["month"])
            t[k] = t[k].drop_duplicates(["month", "operator"] + (["lsa"] if k == "active" else []))
    return t


# --- M2M (machine-to-machine) SIMs ------------------------------------------------------------------------
# From the December 2025 report on, TRAI's "wireless (mobile)" count = consumer SIMs + M2M SIMs. Airtel's count
# jumped by about its M2M base that month while Jio's, Vi's and BSNL's didn't, i.e. they already included M2M.
# The text of each report gives the M2M total and every operator's share, which lets us rebuild consumer SIMs.

M2M_TOTAL = re.compile(r"M2M cellular mobile connections (?:increased|decreased) from ([\d.,]+) million.{0,120}?"
                       r"to ([\d.,]+) million", re.I | re.S)
M2M_SHARES = re.compile(r"Bharti Airtel Limited has the highest number of M2M cellular mobile connections of "
                        r"([\d.]+) million with a market share of ([\d.]+) ?%,? followed by (.{0,160}?) with "
                        r"market share of ([\d.]+) ?%,? ([\d.]+) ?% and ([\d.]+) ?%", re.I | re.S)


def m2m_from_text(text: str, month: date) -> list[dict]:
    t = " ".join(text.split())
    total, shares = M2M_TOTAL.search(t), M2M_SHARES.search(t)
    if not (total and shares):
        return []
    tot = float(total.group(2).replace(",", ""))
    names = [n.strip() for n in re.split(r",| and ", shares.group(3)) if n.strip()]
    ops = []
    for n in names:
        k = squash(n)
        ops.append("Jio" if "jio" in k else "Vi" if "vodafone" in k else "BSNL" if "bsnl" in k else None)
    rows = [{"month": month, "operator": "Airtel", "m2m": float(shares.group(1)) * 1e6}]
    for op, pct in zip(ops, shares.group(4, 5, 6)):
        if op:
            rows.append({"month": month, "operator": op, "m2m": tot * float(pct) / 100 * 1e6})
    return rows


def month_from_title(title: str) -> date | None:
    m = re.search(r"([A-Za-z]+),?\s+(\d{4})\s*$", title.strip())
    if m and m.group(1).lower() in MONTHS:
        return date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
    return None


def build_m2m(raw: str | Path = "data/raw") -> pd.DataFrame:
    import json
    titles = {r["url"].rsplit("/", 1)[1]: r["title"] for r in json.load(open(Path(raw) / "report_index.json"))}
    rows = []
    for f in sorted(Path(raw).glob("*.pdf")):
        month = month_from_title(titles.get(f.name, ""))
        if not month:
            continue
        with pdfplumber.open(f) as pdf:
            text = " ".join((p.extract_text() or "") for p in pdf.pages)
        rows += m2m_from_text(text, month)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["month"] = pd.to_datetime(df["month"])
    return df
