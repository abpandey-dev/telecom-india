"""Jio vs Airtel (and Vi, BSNL): what TRAI's numbers say.

Two clean views, because TRAI changed its definition in December 2025 (wireless mobile = consumer SIMs + M2M
SIMs, which added Airtel's ~66M machine connections in one month):
  reported   Feb 2024 - Nov 2025, as published: every operator's definition is unchanged, circle level is valid
  consumer   Apr 2025 - Aug 2026, national: mobile minus M2M SIMs (Jio, Vi and BSNL counted M2M throughout,
             Airtel only from Dec 2025), using the M2M total and operator shares stated in each report
"""

from __future__ import annotations

import pandas as pd

OPS = ["Jio", "Airtel", "Vi", "BSNL"]
BREAK = pd.Timestamp("2025-12-01")  # first month with Airtel's M2M SIMs inside the mobile count
TARIFF_HIKE = pd.Timestamp("2024-07-01")  # Jio, Airtel and Vi raised prepaid tariffs in early July 2024


def national(mobile: pd.DataFrame) -> pd.DataFrame:
    return mobile.groupby(["month", "operator"])["subscribers"].sum().unstack().reindex(columns=OPS)


def reported(mobile: pd.DataFrame) -> pd.DataFrame:
    return national(mobile).loc[:BREAK - pd.offsets.MonthBegin(1)]


def consumer(mobile: pd.DataFrame, m2m: pd.DataFrame) -> pd.DataFrame:
    """Consumer SIMs = mobile minus M2M, for the months where every operator's M2M is known."""
    nat = national(mobile)
    mm = m2m.pivot_table(index="month", columns="operator", values="m2m").reindex(columns=OPS)
    mm = mm.dropna()
    c = nat.loc[nat.index.intersection(mm.index)].copy()
    for op in ["Jio", "Vi", "BSNL"]:
        c[op] = c[op] - mm[op]
    after = c.index >= BREAK
    c.loc[after, "Airtel"] = c.loc[after, "Airtel"] - mm.loc[c.index[after], "Airtel"]
    return c


def shares(df: pd.DataFrame) -> pd.DataFrame:
    return df.div(df.sum(axis=1), axis=0) * 100


def tariff_shock(rep: pd.DataFrame) -> pd.DataFrame:
    """Net adds in the four months after the July 2024 hike, and in the following eight months."""
    adds = rep.diff()
    return pd.DataFrame({
        "jul_oct_2024": adds.loc["2024-07":"2024-10"].sum(),
        "nov_2024_jun_2025": adds.loc["2024-11":"2025-06"].sum(),
    }) / 1e6


def circle_table(mobile: pd.DataFrame, month: str) -> pd.DataFrame:
    p = mobile[mobile["month"] == month].pivot_table(index="lsa", columns="operator", values="subscribers")
    return p.reindex(columns=OPS)


def circle_shift(mobile: pd.DataFrame, start: str = "2024-02-01", end: str = "2025-11-01") -> pd.DataFrame:
    a, b = shares(circle_table(mobile, start)), shares(circle_table(mobile, end))
    out = (b - a).rename(columns=lambda c: f"{c}_pts")
    out["leader_then"], out["leader_now"] = a.idxmax(axis=1), b.idxmax(axis=1)
    out["jio_airtel_gap_now"] = b["Jio"] - b["Airtel"]
    return out.sort_values("Airtel_pts")


def active_adjusted(mobile: pd.DataFrame, active: pd.DataFrame, month: str = "2025-11-01") -> pd.DataFrame:
    """Share of subscribers vs share of *active* subscribers (VLR %, capped at 100) in one month."""
    subs = circle_table(mobile, month)
    act = active[active["month"] == month].pivot_table(index="lsa", columns="operator", values="active_pct")
    rows = {}
    for op in OPS:
        j = pd.concat([subs[op], act.get(op)], axis=1, keys=["subs", "pct"]).dropna()
        rows[op] = {"subscribers": j["subs"].sum(), "active": (j["subs"] * j["pct"].clip(upper=100) / 100).sum()}
    out = pd.DataFrame(rows).T
    out["active_pct"] = out["active"] / out["subscribers"] * 100
    out["share_of_subscribers"] = out["subscribers"] / out["subscribers"].sum() * 100
    out["share_of_active"] = out["active"] / out["active"].sum() * 100
    return out


def rural_share(rural: pd.DataFrame, mobile: pd.DataFrame, month: str = "2025-11-01") -> pd.Series:
    r = rural[rural["month"] == month].set_index("operator")["rural_subscribers"].reindex(OPS)
    return r / national(mobile).loc[month] * 100
