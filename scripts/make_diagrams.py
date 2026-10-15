"""Draw docs/how-it-works.svg and docs/what-we-get.svg from data/findings.json."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from diagram_kit import BODY, INK, MUTED, arrow, box, card, hbar, lane, lines, panel, svg, t  # noqa: E402

F = json.loads(Path("data/findings.json").read_text())
cov, cs, act = F["coverage"], F["consumer_share"], F["active"]

b = [lane(24, 104, 1152, 236, "blue", "EXTRACT · 30 official TRAI reports, every month verified")]
b.append(box(44, 144, 250, 160, "slate", "TRAI monthly PDFs",
             ["Telecom Subscription Data", f"{cov['first'][:7]} to {cov['last'][:7]}", "operator x 22 circles",
              "downloaded politely"], plain=True))
b.append(box(330, 144, 290, 160, "blue", "Position-based table reader",
             ["rebuilds rows from characters:", "ruled, unruled and sideways", "tables; glued month headers;",
              "each report also gives the", "previous month, filling gaps"]))
b.append(box(656, 144, 250, 160, "green", "Self-checks",
             ["circles must add up to", "TRAI's Total row, per", "operator and month",
              "1,693 overlapping cells:", "99.94% identical"]))
b.append(box(942, 144, 214, 160, "amber", "Definition fix",
             ["Dec 2025: M2M SIMs", "added to 'mobile'", f"Airtel +{F['airtel_break_jump_m']:.1f}M overnight",
              "-> consumer-SIM series"]))
b += [arrow(294, 224, 326, 224), arrow(620, 224, 652, 224), arrow(906, 224, 938, 224)]
b.append(lane(24, 360, 1152, 280, "violet", "ANALYSE · pandas, plus a Claude assistant over the same tables"))
b.append(box(44, 400, 205, 210, "violet", "Consumer race", ["Jio vs Airtel vs Vi", "vs BSNL, consumer", "SIMs only (mobile", "minus M2M)"]))
b.append(box(266, 400, 205, 210, "violet", "Tariff shock", ["July 2024 price", "hikes: who lost,", "who gained, who", "won them back"]))
b.append(box(488, 400, 205, 210, "violet", "Circle battle", ["share shift per", "circle, leaders", "and close races"]))
b.append(box(710, 400, 205, 210, "violet", "Real vs paper SIMs", ["share of SIMs active", "(VLR), active-", "adjusted share,", "rural share"]))
b.append(box(932, 400, 224, 210, "blue", "Ask the data", ["Claude + 7 read-only", "tools over the tables", "every number in the", "answer is checked", "against tool outputs"]))
Path("docs/how-it-works.svg").write_text(svg(1200, 660, "Jio vs Airtel: how it works",
    "India's mobile market from TRAI's own monthly reports, extracted, verified and corrected", "\n".join(b)))

b = [panel(24, 104, 560, 330, "Consumer SIM share", f"{cs['first'][:7]} to {cs['last'][:7]} (mobile minus M2M)")]
colors = {"Jio": "#2563EB", "Airtel": "#EA580C", "Vi": "#0F766E", "BSNL": "#D97706"}
for i, op in enumerate(["Jio", "Airtel", "Vi", "BSNL"]):
    v = cs["end"][op]
    b.append(hbar(34, 170 + i * 44, op, v, 50, 300, colors[op], f"{v:.1f}%", label_w=110, bold=op in ("Jio", "Airtel")))
gap = F["consumer_gap_jio_airtel_m"]
b.append(lines(44, 372, [f"Jio's lead over Airtel grew from {gap['start']:.0f}M to {gap['end']:.0f}M consumer SIMs.",
                         "Airtel's 2026 'surge' in headlines is mostly M2M SIMs."], 13, BODY, 22))
ts = F["tariff_shock_m"]
b.append(panel(608, 104, 568, 330, "The July 2024 tariff shock", "net additions, millions"))
for i, op in enumerate(["Jio", "Vi", "Airtel", "BSNL"]):
    v = ts["jul_oct_2024"][op]
    b.append(t(628, 214 + i * 30, op, 14, INK, 600))
    b.append(t(800, 214 + i * 30, f"{v:+.1f}M", 14, "#B91C1C" if v < 0 else "#15803D", 700, "end"))
    w = ts["nov_2024_jun_2025"][op]
    b.append(t(960, 214 + i * 30, f"{w:+.1f}M", 14, "#B91C1C" if w < 0 else "#15803D", 700, "end"))
b.append(t(800, 184, "Jul-Oct 2024", 11, MUTED, anchor="end"))
b.append(t(960, 184, "next 8 months", 11, MUTED, anchor="end"))
b.append(lines(628, 356, ["BSNL picked up 6.8M switchers, then gave back a third.",
                          "Jio lost 16.5M and won all of them back."], 13, BODY, 22))
lead = F["circle_leaders"]["Nov 2025"]
b.append(card(24, 458, 276, 182, "blue", f"{lead['Jio']} vs {lead['Airtel']}", "circles led by Jio vs Airtel",
              ["Bihar flipped to Jio; Delhi is", f"the closest race ({F['closest_races_pts']['Delhi']:.1f} points)",
               "(Nov 2025, 22 circles)"], big_size=30))
b.append(card(316, 458, 276, 182, "amber", f"{act['BSNL']['active_pct']:.0f}%", "of BSNL SIMs are active",
              [f"vs {act['Jio']['active_pct']:.0f}% for Jio and Airtel: count", "active SIMs and BSNL's share",
               f"drops from {act['BSNL']['share_of_subscribers']:.1f}% to {act['BSNL']['share_of_active']:.1f}%"]))
b.append(card(608, 458, 276, 182, "green", f"{F['vi_circles_lost_share']}/22", "circles where Vi lost share",
              [f"Vi loses ~{-F['consumer_net_adds_per_month_m']['Vi']:.1f}M consumer SIMs", "a month",
               "(Apr 2025 - Aug 2026)"], big_size=30))
b.append(card(900, 458, 276, 182, "purple", f"{F['rural_share_of_base_pct']['Airtel']:.0f}%", "of Airtel's base is rural",
              [f"Jio {F['rural_share_of_base_pct']['Jio']:.0f}%, Vi {F['rural_share_of_base_pct']['Vi']:.0f}%, "
               f"BSNL {F['rural_share_of_base_pct']['BSNL']:.0f}%", "(Nov 2025)"]))
Path("docs/what-we-get.svg").write_text(svg(1200, 660, "Jio vs Airtel: what we get from it",
    f"{cov['months']} months · 22 circles · {cov['reports']} TRAI reports · every month checked against TRAI's totals",
    "\n".join(b)))
print("diagrams written")
