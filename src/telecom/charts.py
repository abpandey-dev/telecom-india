"""Charts. Operators keep fixed colours everywhere: Jio blue, Airtel orange, Vi aqua, BSNL yellow."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

COLORS = {"Jio": "#2a78d6", "Airtel": "#eb6834", "Vi": "#1baf7a", "BSNL": "#eda100"}
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
})


def _grid(ax, axis="y"):
    ax.grid(axis=axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def share_lines(sh: pd.DataFrame, title: str, note: str | None = None, mark: dict | None = None):
    fig, ax = plt.subplots(figsize=(8, 3.9))
    for op in sh.columns:
        ax.plot(sh.index, sh[op], color=COLORS[op], linewidth=2, label=op)
        ax.annotate(f"{op} {sh[op].iloc[-1]:.1f}%", (sh.index[-1], sh[op].iloc[-1]), textcoords="offset points",
                    xytext=(6, -3), fontsize=9, color=INK2)
    for x, label in (mark or {}).items():
        ax.axvline(x, color=MUTED, linestyle="--", linewidth=1)
        ax.text(x, ax.get_ylim()[1], " " + label, fontsize=8.5, color=MUTED, va="top")
    ax.set_ylabel("share of subscribers (%)")
    ax.set_title(title)
    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    ax.set_xlim(sh.index[0], sh.index[-1] + pd.Timedelta(days=75))
    if note:
        fig.text(0.01, 0.005, note, fontsize=8.5, color=MUTED)
    _grid(ax)
    fig.tight_layout()
    return fig


def net_adds(adds: pd.DataFrame, title: str, mark=None):
    fig, ax = plt.subplots(figsize=(8, 3.9))
    width = 6
    for k, op in enumerate(adds.columns):
        ax.bar(adds.index + pd.Timedelta(days=(k - 1.5) * width), adds[op], width=width, color=COLORS[op], label=op)
    ax.axhline(0, color=INK2, linewidth=0.8)
    if mark is not None:
        ax.axvline(mark, color=MUTED, linestyle="--", linewidth=1)
        ax.text(mark, ax.get_ylim()[0], " tariff hikes", fontsize=8.5, color=MUTED, va="bottom")
    ax.set_ylabel("net additions (millions)")
    ax.set_title(title)
    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    _grid(ax)
    fig.tight_layout()
    return fig


def circle_shift(cs: pd.DataFrame):
    d = cs.sort_values("Airtel_pts")
    fig, ax = plt.subplots(figsize=(8, 7))
    y = range(len(d))
    ax.barh([i + 0.2 for i in y], d["Airtel_pts"], height=0.38, color=COLORS["Airtel"], label="Airtel")
    ax.barh([i - 0.2 for i in y], d["Jio_pts"], height=0.38, color=COLORS["Jio"], label="Jio")
    ax.set_yticks(list(y), [f"{n}  ({lead})" if lead != then else n
                             for n, lead, then in zip(d.index, d["leader_now"], d["leader_then"])])
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_xlabel("change in share of the circle, Feb 2024 to Nov 2025 (percentage points)")
    ax.set_title("Who gained share where, Feb 2024 to Nov 2025 (bracket = leader changed)")
    ax.legend(frameon=False, loc="lower right")
    _grid(ax, "x")
    fig.tight_layout()
    return fig


def leaders(cs_now: pd.DataFrame):
    """Jio minus Airtel share in each circle (Nov 2025): positive = Jio leads."""
    d = cs_now.sort_values("jio_airtel_gap_now")
    fig, ax = plt.subplots(figsize=(8, 7))
    colors = [COLORS["Jio"] if v > 0 else COLORS["Airtel"] for v in d["jio_airtel_gap_now"]]
    ax.barh(d.index, d["jio_airtel_gap_now"], color=colors, height=0.62)
    for i, v in enumerate(d["jio_airtel_gap_now"]):
        ax.text(v + (0.4 if v >= 0 else -0.4), i, f"{v:+.1f}", va="center", ha="left" if v >= 0 else "right",
                fontsize=8.5, color=INK2)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_xlabel("Jio share minus Airtel share (percentage points)  ·  blue = Jio leads, orange = Airtel leads")
    ax.set_title("The circle-by-circle race (Nov 2025)")
    _grid(ax, "x")
    fig.tight_layout()
    return fig


def active(aa: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    x = range(len(aa))
    ax.bar([i - 0.2 for i in x], aa["share_of_subscribers"], width=0.38, color="#b9b8b2", label="share of all SIMs")
    ax.bar([i + 0.2 for i in x], aa["share_of_active"], width=0.38, color=[COLORS[o] for o in aa.index],
           label="share of active SIMs")
    for i, (s, a, p) in enumerate(zip(aa["share_of_subscribers"], aa["share_of_active"], aa["active_pct"])):
        ax.text(i + 0.2, a + 0.8, f"{a:.1f}%", ha="center", fontsize=9, color=INK2)
        ax.text(i - 0.2, s + 0.8, f"{s:.1f}%", ha="center", fontsize=9, color=MUTED)
        ax.text(i, -4.5, f"{p:.0f}% of SIMs active", ha="center", fontsize=8.5, color=INK2)
    ax.set_xticks(list(x), aa.index)
    ax.set_ylim(-6, aa[["share_of_subscribers", "share_of_active"]].values.max() * 1.18)
    ax.set_ylabel("market share (%)")
    ax.set_title("Count only active SIMs and BSNL shrinks by a third (Nov 2025)")
    ax.legend(frameon=False, loc="upper right")
    _grid(ax)
    fig.tight_layout()
    return fig


def save(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
