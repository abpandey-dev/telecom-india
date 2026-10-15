"""Assistant tools and agent loop with a scripted fake Claude: no API calls, no cost."""

import json
from types import SimpleNamespace as NS

import pytest

from telecom.assistant import ANSWER_SCHEMA, FALLBACK_BETA, Assistant, Data, ToolError, Tools, unverified_numbers


@pytest.fixture(scope="module")
def data():
    return Data()  # the verified CSVs shipped in data/processed/


def test_tools_return_verified_numbers(data):
    t = Tools(data)
    ms = json.loads(t.call("market_share", {"view": "consumer", "month": "2026-08"}))
    assert ms["operators"]["Jio"]["share_pct"] == 41.8 and ms["operators"]["Airtel"]["share_pct"] == 35.2
    bihar = json.loads(t.call("circle", {"lsa": "bihar", "month": "latest"}))
    assert bihar["circle"] == "Bihar" and bihar["leader"] == "Jio" and bihar["month"] == "2025-11"
    shock = json.loads(t.call("tariff_shock", {}))
    assert shock["Jio"]["jul_oct_2024_m"] == -16.5 and shock["BSNL"]["jul_oct_2024_m"] == 6.8
    top = json.loads(t.call("rank_circles", {"metric": "airtel_share_change", "top": 1}))
    assert top[0]["circle"] == "Tamil Nadu"
    act = json.loads(t.call("active_sims", {"lsa": "India"}))
    assert act["operators"]["BSNL"]["active_pct"] < 60


def test_tool_errors_are_helpful(data):
    t = Tools(data)
    with pytest.raises(ToolError, match="no Dec 2025"):
        t.call("market_share", {"view": "consumer", "month": "2025-12"})
    with pytest.raises(ToolError, match="unknown circle"):
        t.call("circle", {"lsa": "Atlantis", "month": "latest"})


def test_number_check_flags_invented_numbers():
    outputs = ['{"Jio": {"share_pct": 41.8}, "gap": 75.8}']
    assert unverified_numbers("Jio holds 41.8% and leads by 75.8M (Aug 2026, 13 circles).", outputs) == []
    assert unverified_numbers("Jio holds 43.1% of the market.", outputs) == ["43.1"]
    assert unverified_numbers("about 76M", outputs) == []  # 75.8 rounded to a whole number is fine
    assert unverified_numbers("a lead of 81M", outputs) == ["81"]
    assert unverified_numbers("1,234,567 SIMs", ['{"x": 1234567}']) == []


def tool_use(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def resp(content, stop):
    return NS(content=content, stop_reason=stop, usage=NS(input_tokens=300, output_tokens=60))


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return self.responses.pop(0)


def final(text, nums):
    return resp([NS(type="text", text=json.dumps({"answer": text, "key_numbers": nums, "caveats": []}))], "end_turn")


def test_agent_loop_grounded_answer(data):
    client = FakeClient([
        resp([tool_use("a", "market_share", {"view": "consumer", "month": "latest"}),
              tool_use("b", "data_notes", {})], "tool_use"),
        final("On consumer SIMs Jio has 41.8% and Airtel 35.2%.", [{"label": "Jio share", "value": "41.8%"}]),
    ])
    r = Assistant(data=data, client=client).ask("Who leads, Jio or Airtel?")
    assert r.error is None and r.unverified == []
    assert [t["tool"] for t in r.trace] == ["market_share", "data_notes"]
    first = client.calls[0]
    assert first["fallbacks"] == "default" and first["betas"] == [FALLBACK_BETA]
    assert first["output_config"]["format"]["schema"] == ANSWER_SCHEMA
    assert len(client.calls[1]["messages"][-1]["content"]) == 2  # both tool results in one message


def test_agent_flags_a_made_up_number(data):
    client = FakeClient([
        resp([tool_use("a", "market_share", {"view": "consumer", "month": "latest"})], "tool_use"),
        final("Jio has 47.3% of the market.", []),
    ])
    r = Assistant(data=data, client=client, model="claude-haiku-5-5").ask("Jio share?")
    assert r.unverified == ["47.3"]
    assert "fallbacks" not in client.calls[0]  # Haiku 5.5 has no server-side fallbacks


def test_refusal_is_reported(data):
    r = Assistant(data=data, client=FakeClient([resp([], "refusal")])).ask("x")
    assert r.answer is None and "declined" in r.error
