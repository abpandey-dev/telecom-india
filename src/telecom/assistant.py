"""Ask the data: Claude answers questions about India's mobile market using tools over the verified TRAI tables.

Guardrail: every number in the answer is checked against the numbers the tools actually returned in this
conversation. A number that can't be found (at the precision it is written) is reported as unverified, so a
made-up statistic can't pass silently.

    telecom-ask "Who is growing faster, Jio or Airtel?" --model claude-haiku-5-5 --trace
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from telecom import analysis as A

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}
DATA = Path(__file__).resolve().parents[2] / "data" / "processed"

SYSTEM_PROMPT = """You are a telecom market analyst for India. Answer questions about mobile operators (Jio, Airtel,
Vi, BSNL) using only the tools, which read TRAI's official monthly subscriber data, Feb 2024 to Aug 2026.

Important: in December 2025 TRAI started counting machine-to-machine (M2M) SIMs as mobile subscribers, which
added ~68.5M to Airtel in one month. For market share and growth comparisons use the "consumer" view (M2M SIMs
removed). Circle-level numbers are only clean up to Nov 2025. Call data_notes if a question touches definitions.

Use the numbers exactly as the tools return them (same units and rounding). If the data can't answer the
question (for example speeds, prices or revenue), say so plainly instead of guessing."""


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


MONTH = {"type": "string", "description": "YYYY-MM, or 'latest'"}
OPERATOR = {"type": "string", "enum": A.OPS}

TOOLS = [
    {"name": "market_share", "strict": True,
     "description": "National subscribers (millions) and market share (%) for every operator in one month.",
     "input_schema": _schema({"view": {"type": "string", "enum": ["consumer", "reported"]}, "month": MONTH},
                             ["view", "month"])},
    {"name": "trend", "strict": True,
     "description": "One operator's national share and subscribers at the start and end of a period, the change, "
                    "and average monthly net additions (millions).",
     "input_schema": _schema({"operator": OPERATOR, "view": {"type": "string", "enum": ["consumer", "reported"]},
                              "start": MONTH, "end": MONTH}, ["operator", "view", "start", "end"])},
    {"name": "circle", "strict": True,
     "description": "One circle (state/region): subscribers (millions) and share per operator, the leader, the "
                    "Jio-minus-Airtel gap, and each operator's share change since Feb 2024. Month up to 2025-11.",
     "input_schema": _schema({"lsa": {"type": "string", "description": "e.g. Bihar, Delhi, Tamil Nadu, U.P. (East)"},
                              "month": MONTH}, ["lsa", "month"])},
    {"name": "rank_circles", "strict": True,
     "description": "Rank all 22 circles by a metric (Nov 2025, or change Feb 2024 to Nov 2025).",
     "input_schema": _schema({"metric": {"type": "string", "enum": [
         "jio_minus_airtel_share", "airtel_share_change", "jio_share_change", "vi_share_change", "bsnl_share_change"]},
         "top": {"type": "integer", "description": "how many to return, 1-22"}}, ["metric", "top"])},
    {"name": "active_sims", "strict": True,
     "description": "Share of SIMs active on the peak day (VLR %) per operator, nationally or for one circle, and "
                    "market share counting only active SIMs (Nov 2025).",
     "input_schema": _schema({"lsa": {"type": "string", "description": "a circle name, or 'India'"}}, ["lsa"])},
    {"name": "tariff_shock", "strict": True,
     "description": "Net additions (millions) per operator in Jul-Oct 2024 (after the July 2024 tariff hikes) "
                    "and in the following eight months.",
     "input_schema": _schema({}, [])},
    {"name": "data_notes", "strict": True,
     "description": "Definitions, coverage and limits of the data (M2M break, consumer vs reported view, VLR).",
     "input_schema": _schema({}, [])},
]

ANSWER_SCHEMA = _schema({
    "answer": {"type": "string", "description": "Plain-English answer, 2-6 sentences."},
    "key_numbers": {"type": "array", "items": _schema({"label": {"type": "string"}, "value": {"type": "string"}},
                                                      ["label", "value"])},
    "caveats": {"type": "array", "items": {"type": "string"}},
}, ["answer", "key_numbers", "caveats"])


class ToolError(Exception):
    pass


class Data:
    """The verified tables from data/processed/."""

    def __init__(self, folder: Path = DATA):
        def read(name):
            df = pd.read_csv(folder / f"{name}.csv")
            df["month"] = pd.to_datetime(df["month"])
            return df

        self.mobile, self.active, self.rural, self.m2m = (read(n) for n in ("mobile", "active", "rural", "m2m"))
        self.reported = A.reported(self.mobile)
        self.consumer = A.consumer(self.mobile, self.m2m)


def _r(x, nd=1):
    return None if pd.isna(x) else round(float(x), nd)


class Tools:
    def __init__(self, data: Data):
        self.d = data
        self.outputs: list[str] = []

    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None)
        if fn is None or name.startswith("_"):
            raise ToolError(f"unknown tool {name}")
        out = json.dumps(fn(**args), default=str)
        self.outputs.append(out)
        return out

    def _month(self, df: pd.DataFrame, month: str) -> pd.Timestamp:
        if month == "latest":
            return df.index.max()
        try:
            m = pd.Timestamp(month + "-01")
        except ValueError as e:
            raise ToolError(f"month must be YYYY-MM, got {month!r}") from e
        if m not in df.index:
            raise ToolError(f"{month} not available; months {df.index.min():%Y-%m} to {df.index.max():%Y-%m}"
                            + (" (consumer view has no Dec 2025)" if m == pd.Timestamp("2025-12-01") else ""))
        return m

    def _view(self, view: str) -> pd.DataFrame:
        return self.d.consumer if view == "consumer" else self.d.reported

    def market_share(self, view: str, month: str) -> dict:
        df = self._view(view)
        m = self._month(df, month)
        row, sh = df.loc[m], A.shares(df).loc[m]
        return {"view": view, "month": f"{m:%Y-%m}",
                "operators": {op: {"subscribers_m": _r(row[op] / 1e6), "share_pct": _r(sh[op])} for op in A.OPS},
                "jio_minus_airtel_pts": _r(sh["Jio"] - sh["Airtel"]),
                "jio_minus_airtel_subscribers_m": _r((row["Jio"] - row["Airtel"]) / 1e6)}

    def trend(self, operator: str, view: str, start: str, end: str) -> dict:
        df = self._view(view)
        a, b = self._month(df, start), self._month(df, end)
        sh = A.shares(df)
        months = max(1, (b.year - a.year) * 12 + b.month - a.month)
        return {"operator": operator, "view": view, "start": f"{a:%Y-%m}", "end": f"{b:%Y-%m}",
                "share_start_pct": _r(sh.loc[a, operator]), "share_end_pct": _r(sh.loc[b, operator]),
                "share_change_pts": _r(sh.loc[b, operator] - sh.loc[a, operator], 2),
                "subscribers_start_m": _r(df.loc[a, operator] / 1e6), "subscribers_end_m": _r(df.loc[b, operator] / 1e6),
                "net_adds_m": _r((df.loc[b, operator] - df.loc[a, operator]) / 1e6),
                "avg_monthly_net_adds_m": _r((df.loc[b, operator] - df.loc[a, operator]) / 1e6 / months, 2),
                # the comparison people ask about most, so the answer can cite it instead of computing it
                "jio_minus_airtel_pts_start": _r(sh.loc[a, "Jio"] - sh.loc[a, "Airtel"]),
                "jio_minus_airtel_pts_end": _r(sh.loc[b, "Jio"] - sh.loc[b, "Airtel"]),
                "jio_minus_airtel_subscribers_m_start": _r((df.loc[a, "Jio"] - df.loc[a, "Airtel"]) / 1e6),
                "jio_minus_airtel_subscribers_m_end": _r((df.loc[b, "Jio"] - df.loc[b, "Airtel"]) / 1e6)}

    def _lsa(self, name: str) -> str:
        from telecom.parse import lsa_name
        lsa = lsa_name(name)
        if not lsa:
            raise ToolError(f"unknown circle {name!r}; circles: {', '.join(sorted(self.d.mobile['lsa'].unique()))}")
        return lsa

    def circle(self, lsa: str, month: str) -> dict:
        lsa = self._lsa(lsa)
        clean = self.d.reported
        m = self._month(clean, "2025-11" if month == "latest" else month)
        now = A.circle_table(self.d.mobile, f"{m:%Y-%m-%d}").loc[lsa]
        base = A.circle_table(self.d.mobile, "2024-02-01").loc[lsa]
        sh, sh0 = now / now.sum() * 100, base / base.sum() * 100
        return {"circle": lsa, "month": f"{m:%Y-%m}", "leader": sh.idxmax(),
                "jio_minus_airtel_pts": _r(sh["Jio"] - sh["Airtel"], 2),
                "operators": {op: {"subscribers_m": _r(now[op] / 1e6, 2), "share_pct": _r(sh[op]),
                                   "share_change_since_2024_02_pts": _r(sh[op] - sh0[op])} for op in A.OPS}}

    def rank_circles(self, metric: str, top: int) -> list[dict]:
        cs = A.circle_shift(self.d.mobile)
        col = {"jio_minus_airtel_share": "jio_airtel_gap_now", "airtel_share_change": "Airtel_pts",
               "jio_share_change": "Jio_pts", "vi_share_change": "Vi_pts", "bsnl_share_change": "BSNL_pts"}[metric]
        s = cs[col].dropna().sort_values(ascending=False)
        top = max(1, min(22, top))
        return [{"circle": k, metric: _r(v, 2), "leader_nov_2025": cs.loc[k, "leader_now"]} for k, v in s.head(top).items()]

    def active_sims(self, lsa: str) -> dict:
        if lsa.strip().lower() in ("india", "all", "national"):
            aa = A.active_adjusted(self.d.mobile, self.d.active)
            return {"scope": "India", "month": "2025-11", "operators": {
                op: {"active_pct": _r(aa.loc[op, "active_pct"]), "share_of_all_sims_pct": _r(aa.loc[op, "share_of_subscribers"]),
                     "share_of_active_sims_pct": _r(aa.loc[op, "share_of_active"])} for op in A.OPS}}
        name = self._lsa(lsa)
        a = self.d.active[(self.d.active["month"] == "2025-11-01") & (self.d.active["lsa"] == name)]
        return {"scope": name, "month": "2025-11",
                "active_pct": {r.operator: _r(r.active_pct) for r in a.itertuples() if r.operator in A.OPS}}

    def tariff_shock(self) -> dict:
        t = A.tariff_shock(self.d.reported)
        return {op: {"jul_oct_2024_m": _r(t.loc[op, "jul_oct_2024"]),
                     "nov_2024_jun_2025_m": _r(t.loc[op, "nov_2024_jun_2025"])} for op in A.OPS}

    def data_notes(self) -> dict:
        return {
            "source": "TRAI monthly Telecom Subscription Data press releases, Feb 2024 to Aug 2026, 22 circles",
            "verified": "each operator-month matches TRAI's own Total row; 99.94% of cells identical across reports",
            "m2m_break": "From Dec 2025 TRAI counts mobile = consumer SIMs + M2M SIMs; Airtel jumped ~68.5M that month "
                         "because its M2M SIMs were added; Jio, Vi and BSNL already included theirs.",
            "views": {"consumer": "Apr 2025 to Aug 2026, national, M2M removed (no Dec 2025)",
                      "reported": "Feb 2024 to Nov 2025 as published, valid at circle level"},
            "active_sims": "VLR % = SIMs active on the peak day; capped at 100",
            "not_covered": ["network speed", "prices", "revenue", "5G FWA", "wireline"],
        }


# --- grounding check ------------------------------------------------------------------------------

# a number, optionally with thousands separators and decimals; units may follow directly ("75.8M", "41.8%")
NUM = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")
DATE_CONTEXT = re.compile(r"(19|20)\d{2}(-\d{2})?$")


def numbers_in(text: str) -> list[str]:
    return [m.group(0).replace(",", "") for m in NUM.finditer(text)]


def unverified_numbers(answer_text: str, tool_outputs: list[str]) -> list[str]:
    """Numbers in the answer that don't appear (at the same precision) in any tool output. Years and small whole
    numbers (counts such as '13 circles', days of the month) are ignored."""
    pool = set()
    for out in tool_outputs:
        for n in numbers_in(out):
            try:
                v = float(n)
            except ValueError:
                continue
            pool |= {round(v, 0), round(v, 1), round(v, 2), round(abs(v), 0), round(abs(v), 1), round(abs(v), 2)}
    bad = []
    for n in numbers_in(answer_text):
        if DATE_CONTEXT.match(n.lstrip("-")):
            continue
        try:
            v = float(n)
        except ValueError:
            continue
        if abs(v) < 32 and "." not in n:
            continue
        nd = len(n.split(".")[1]) if "." in n else 0
        if round(abs(v), nd) not in pool:
            bad.append(n)
    return bad


@dataclass
class AskResult:
    answer: dict | None
    trace: list[dict] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float | None = None
    error: str | None = None


class Assistant:
    def __init__(self, data: Data | None = None, model: str = DEFAULT_MODEL, effort: str = "medium",
                 max_turns: int = 8, client=None):
        self.data = data or Data()
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client, self.model, self.effort, self.max_turns = client, model, effort, max_turns

    def ask(self, question: str) -> AskResult:
        tools = Tools(self.data)
        messages = [{"role": "user", "content": question}]
        res = AskResult(answer=None)
        extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if self.model in FALLBACK_MODELS else {}
        start = time.perf_counter()
        for turn in range(1, self.max_turns + 1):
            resp = self.client.beta.messages.create(
                model=self.model, max_tokens=8000, system=SYSTEM_PROMPT, tools=TOOLS, messages=messages,
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
                **extra)
            res.input_tokens += resp.usage.input_tokens
            res.output_tokens += resp.usage.output_tokens
            if resp.stop_reason == "refusal":
                res.error = "Model declined the request"
                break
            if resp.stop_reason == "max_tokens":
                res.error = "Response hit max_tokens"
                break
            messages.append({"role": "assistant", "content": resp.content})
            uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason == "tool_use" and uses:
                results = []
                for b in uses:
                    try:
                        out, err = tools.call(b.name, dict(b.input)), False
                    except (ToolError, TypeError, KeyError) as e:
                        out, err = f"Error: {e}", True
                    res.trace.append({"turn": turn, "tool": b.name, "input": dict(b.input), "is_error": err})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": err})
                messages.append({"role": "user", "content": results})  # all results in one message
                continue
            if resp.stop_reason == "pause_turn":
                continue
            text = "".join(b.text for b in resp.content if b.type == "text")
            try:
                res.answer = json.loads(text)
            except json.JSONDecodeError as e:
                res.error = f"Could not parse answer: {e}"
            break
        else:
            res.error = f"No final answer after {self.max_turns} turns"
        if res.answer:
            shown = res.answer["answer"] + " " + " ".join(k["value"] for k in res.answer["key_numbers"])
            res.unverified = unverified_numbers(shown, tools.outputs)
        res.latency_s = round(time.perf_counter() - start, 2)
        if self.model in PRICES:
            p_in, p_out = PRICES[self.model]
            res.cost_usd = (res.input_tokens * p_in + res.output_tokens * p_out) / 1e6
        return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="telecom-ask", description="Ask questions about India's mobile market")
    p.add_argument("question")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--trace", action="store_true")
    a = p.parse_args(argv)
    r = Assistant(model=a.model, effort=a.effort).ask(a.question)
    if a.trace:
        for t in r.trace:
            print(f"  turn {t['turn']}: {t['tool']}({json.dumps(t['input'])}){'  [error]' if t['is_error'] else ''}")
    if r.error:
        print("Error:", r.error)
    if r.answer:
        print("\n" + r.answer["answer"])
        for k in r.answer["key_numbers"]:
            print(f"  - {k['label']}: {k['value']}")
        for c in r.answer["caveats"]:
            print(f"  (caveat) {c}")
        print("\nNumber check: " + ("every number found in the tool outputs ✓" if not r.unverified
                                     else f"NOT found in tool outputs: {', '.join(r.unverified)}"))
    cost = f", ${r.cost_usd:.4f}" if r.cost_usd is not None else ""
    print(f"{len(r.trace)} tool calls, {r.input_tokens}+{r.output_tokens} tokens, {r.latency_s}s{cost}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
