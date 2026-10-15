import pandas as pd

from telecom import analysis as A


def _mobile(rows):
    df = pd.DataFrame(rows, columns=["month", "lsa", "operator", "subscribers"])
    df["month"] = pd.to_datetime(df["month"])
    return df


def test_consumer_removes_m2m_and_handles_airtels_break():
    rows = []
    for mo, airtel in [("2025-11-01", 100), ("2025-12-01", 170)]:  # Airtel's count jumps by its 70 M2M SIMs
        rows += [(mo, "Delhi", "Airtel", airtel), (mo, "Delhi", "Jio", 200), (mo, "Delhi", "Vi", 50),
                 (mo, "Delhi", "BSNL", 20)]
    m2m = pd.DataFrame([(mo, op, v) for mo in ("2025-11-01", "2025-12-01")
                        for op, v in [("Airtel", 70), ("Jio", 20), ("Vi", 10), ("BSNL", 2)]],
                       columns=["month", "operator", "m2m"])
    m2m["month"] = pd.to_datetime(m2m["month"])
    c = A.consumer(_mobile(rows), m2m)
    assert c.loc["2025-11-01", "Airtel"] == 100  # before the break Airtel's count had no M2M
    assert c.loc["2025-12-01", "Airtel"] == 100  # after it, M2M is removed: no fake jump
    assert c.loc["2025-11-01", "Jio"] == 180 and c.loc["2025-12-01", "Vi"] == 40


def test_tariff_shock_and_circle_shift():
    rows = []
    for mo, jio in [("2024-06-01", 100), ("2024-10-01", 90), ("2025-06-01", 105)]:
        rows += [(mo, "Bihar", "Jio", jio), (mo, "Bihar", "Airtel", 95), (mo, "Bihar", "Vi", 10),
                 (mo, "Bihar", "BSNL", 5)]
    nat = A.national(_mobile(rows))
    shock = A.tariff_shock(nat)
    assert round(shock.loc["Jio", "jul_oct_2024"] * 1e6) == -10 and round(shock.loc["Jio", "nov_2024_jun_2025"] * 1e6) == 15
    cs = A.circle_shift(_mobile(rows), start="2024-10-01", end="2025-06-01")
    assert cs.loc["Bihar", "leader_then"] == "Airtel" and cs.loc["Bihar", "leader_now"] == "Jio"


def test_active_adjusted_caps_at_100():
    m = _mobile([("2025-11-01", "Delhi", op, 100) for op in A.OPS])
    act = pd.DataFrame([("2025-11-01", "Delhi", op, p) for op, p in
                        [("Jio", 110), ("Airtel", 90), ("Vi", 80), ("BSNL", 50)]],
                       columns=["month", "lsa", "operator", "active_pct"])
    act["month"] = pd.to_datetime(act["month"])
    aa = A.active_adjusted(m, act)
    assert aa.loc["Jio", "active_pct"] == 100 and aa.loc["BSNL", "active_pct"] == 50
    assert round(aa["share_of_active"].sum()) == 100
