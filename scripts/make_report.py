"""Parse the TRAI reports, compute the findings and draw the charts.

    PYTHONPATH=src python scripts/make_report.py
"""

import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from telecom import analysis as A
from telecom import charts as C
from telecom.parse import build, build_m2m

IMG = Path("docs/images")
IMG.mkdir(parents=True, exist_ok=True)

t = build()
t["m2m"] = build_m2m()
pickle.dump(t, open("data/tables.pkl", "wb"))
for k in ("mobile", "active", "rural", "m2m"):
    t[k].to_csv(f"data/{k}.csv", index=False)
m, act, rural, m2m = t["mobile"], t["active"], t["rural"], t["m2m"]

nat = A.national(m)
rep = A.reported(m)
cons = A.consumer(m, m2m)
csh = A.shares(cons)
rsh = A.shares(rep)
shock = A.tariff_shock(rep)
shift = A.circle_shift(m)
aa = A.active_adjusted(m, act)
rur = A.rural_share(rural, m)

C.save(C.share_lines(csh, "Consumer SIMs: Jio keeps its lead (Apr 2025 - Aug 2026)",
                     note="Consumer SIMs = mobile minus machine-to-machine (M2M) SIMs. Dec 2025 has no M2M split."),
       IMG / "consumer_share.png")
C.save(C.share_lines(rsh, "Market share as reported (Feb 2024 - Nov 2025)",
                     mark={A.TARIFF_HIKE: "tariff hikes"}), IMG / "reported_share.png")
C.save(C.net_adds((rep.diff() / 1e6).loc["2024-03":"2025-06"], "Net additions per month: the 2024 tariff shock",
                  mark=A.TARIFF_HIKE), IMG / "tariff_net_adds.png")
C.save(C.circle_shift(shift), IMG / "circle_shift.png")
C.save(C.leaders(shift), IMG / "circle_race.png")
C.save(C.active(aa), IMG / "active.png")

# the definition break, shown rather than hidden
fig, ax = plt.subplots(figsize=(8, 3.6))
ax.plot(nat.index, nat["Airtel"] / 1e6, color=C.COLORS["Airtel"], linewidth=2, label="Airtel, as reported")
ax.plot(cons.index, cons["Airtel"] / 1e6, color=C.COLORS["Airtel"], linewidth=2, linestyle=":", marker="o",
        markersize=4, label="Airtel, consumer SIMs")
jump = (nat.loc[A.BREAK, "Airtel"] - nat.loc[A.BREAK - pd.offsets.MonthBegin(1), "Airtel"]) / 1e6
ax.annotate(f"+{jump:.1f}M in one month:\nM2M SIMs added to the count", (A.BREAK, nat.loc[A.BREAK, "Airtel"] / 1e6),
            textcoords="offset points", xytext=(-190, 6), fontsize=9, color=C.INK2,
            arrowprops={"arrowstyle": "->", "color": C.MUTED})
ax.set_ylabel("subscribers (millions)")
ax.set_title("Why the headline numbers mislead: TRAI's Dec 2025 definition change")
ax.legend(frameon=False, loc="upper left")
C._grid(ax)
fig.tight_layout()
C.save(fig, IMG / "definition_break.png")

last, first = cons.index.max(), cons.index.min()
findings = {
    "coverage": {"months": int(m["month"].nunique()), "first": str(m["month"].min().date()),
                 "last": str(m["month"].max().date()), "circles": int(m["lsa"].nunique()),
                 "reports": int(len(t["log"])), "reports_parsed": int(t["log"]["error"].isna().sum())},
    "consumer_share": {"first": str(first.date()), "last": str(last.date()),
                       "start": csh.loc[first].round(2).to_dict(), "end": csh.loc[last].round(2).to_dict()},
    "consumer_gap_jio_airtel_m": {"start": round((cons.loc[first, "Jio"] - cons.loc[first, "Airtel"]) / 1e6, 1),
                                  "end": round((cons.loc[last, "Jio"] - cons.loc[last, "Airtel"]) / 1e6, 1)},
    "consumer_net_adds_per_month_m": (cons.diff().mean() / 1e6).round(2).to_dict(),
    "consumer_millions_end": (cons.loc[last] / 1e6).round(1).to_dict(),
    "reported_millions_end": (nat.loc[nat.index.max()] / 1e6).round(1).to_dict(),
    "airtel_break_jump_m": round(jump, 1),
    "tariff_shock_m": shock.round(2).to_dict(),
    "circle_leaders": {"Feb 2024": shift["leader_then"].value_counts().to_dict(),
                       "Nov 2025": shift["leader_now"].value_counts().to_dict()},
    "leader_changes": {k: [r.leader_then, r.leader_now] for k, r in shift.iterrows() if r.leader_then != r.leader_now},
    "closest_races_pts": shift["jio_airtel_gap_now"].abs().sort_values().head(5).round(2).to_dict(),
    "airtel_gains_pts": shift["Airtel_pts"].sort_values(ascending=False).head(5).round(1).to_dict(),
    "jio_gains_pts": shift["Jio_pts"].sort_values(ascending=False).head(5).round(1).to_dict(),
    "vi_circles_lost_share": int((shift["Vi_pts"] < 0).sum()),
    "active": aa[["active_pct", "share_of_subscribers", "share_of_active"]].round(2).to_dict("index"),
    "rural_share_of_base_pct": rur.round(1).to_dict(),
}
Path("data/findings.json").write_text(json.dumps(findings, indent=1, default=str))
print(json.dumps(findings, indent=1, default=str))
