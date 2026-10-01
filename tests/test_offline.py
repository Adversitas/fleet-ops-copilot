"""Offline tests: no API key or network needed. The agent loop runs against a scripted
fake client, so tool dispatch, tracing and the message protocol are still exercised."""
from types import SimpleNamespace

import pytest

import store
from agent.agent import FleetOpsAgent
from agent.tools import execute_tool
from ingestion.build_ontology import compute_status, normalize_datetime

# --------------------------------------------------------------------------- ingestion


def test_both_date_formats_normalize_to_iso():
    assert normalize_datetime("2026-09-08 06:10") == "2026-09-08T06:10:00"
    assert normalize_datetime("09/08/2026 06:10") == "2026-09-08T06:10:00"
    assert normalize_datetime("  ") is None
    with pytest.raises(ValueError):
        normalize_datetime("8 Sept 2026")


@pytest.mark.parametrize(
    ("sched_arr", "act_arr", "act_dep", "expected"),
    [
        ("2026-09-08T11:00:00", "2026-09-08T10:30:00", "2026-09-08T06:00:00", "on_time"),
        ("2026-09-08T09:00:00", "2026-09-08T09:30:00", "2026-09-08T05:00:00", "late"),
        ("2026-09-08T12:00:00", None, None, "not_departed"),
        ("2026-09-08T10:30:00", None, "2026-09-08T06:00:00", "at_risk"),  # "now" is 10:00
        ("2026-09-08T15:00:00", None, "2026-09-08T06:00:00", "in_progress"),
    ],
)
def test_route_status(sched_arr, act_arr, act_dep, expected):
    assert compute_status(sched_arr, act_arr, act_dep) == expected


# --------------------------------------------------------------------------- tools


def test_select_works():
    rows = execute_tool("query_fleet_db", {"sql": "SELECT vehicle_id FROM vehicles"})
    assert {"vehicle_id": "V-1003"} in rows


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM vehicles",
        "SELECT 1; DROP TABLE vehicles",
        "WITH x AS (SELECT 1) DELETE FROM vehicles",
    ],
)
def test_query_tool_cannot_write(sql):
    result = execute_tool("query_fleet_db", {"sql": sql})
    assert "error" in result
    count = execute_tool("query_fleet_db", {"sql": "SELECT COUNT(*) AS n FROM vehicles"})
    assert count[0]["n"] > 0  # table still intact


def test_driver_notes_surface_what_the_logs_miss():
    hits = execute_tool("search_driver_notes", {"query": "brakes"})
    assert any(h["vehicle_id"] == "V-1003" for h in hits)


def test_weather_mock_is_deterministic():
    a = execute_tool("get_weather_risk", {"route_id": "R-5003"})
    assert a == execute_tool("get_weather_risk", {"route_id": "R-5003"})
    assert a["risk"] in {"low", "medium", "high"}


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        ({"vehicle_id": "V-1006", "message": "x", "severity": "critical"}, "severity"),
        ({"vehicle_id": "V-9999", "message": "x", "severity": "high"}, "Unknown vehicle"),
        ({"vehicle_id": "V-1006", "message": "   ", "severity": "high"}, "message"),
    ],
)
def test_invalid_alerts_are_rejected(args, problem):
    result = execute_tool("propose_alert", args)
    assert problem in result["error"]


def test_alert_needs_human_approval_before_it_exists():
    queued = execute_tool("propose_alert", {"vehicle_id": "V-1006", "message": "Coolant fault",
                                            "severity": "medium"})
    assert queued["status"] == "pending_human_approval"

    def alert_count():
        conn = store.get_db(read_only=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        finally:
            conn.close()

    before = alert_count()
    store.decide_approval(queued["approval_id"], approve=True)
    assert alert_count() == before + 1
    with pytest.raises(ValueError):
        store.decide_approval(queued["approval_id"], approve=False)  # already decided
    assert any(e["kind"] == "decide_approval" for e in store.AUDIT_LOG)


# --------------------------------------------------------------------------- agent loop


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


class FakeClient:
    """Plays back scripted responses and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot
        return self.responses.pop(0)


def test_agent_runs_tools_and_returns_grounded_answer():
    client = FakeClient(
        SimpleNamespace(stop_reason="tool_use", content=[
            text("Checking the routes."),
            tool_use("t1", "query_fleet_db", {"sql": "SELECT route_id FROM routes WHERE status = 'at_risk'"}),
        ]),
        SimpleNamespace(stop_reason="end_turn", content=[text("R-5003 is at risk.")]),
    )
    result = FleetOpsAgent(client=client, model="claude-opus-5-5").run("What's at risk?")

    assert result["reply"] == "R-5003 is at risk."
    assert [step["tool"] for step in result["trace"]] == ["query_fleet_db"]
    tool_msg = client.requests[1]["messages"][-1]
    assert tool_msg["role"] == "user" and tool_msg["content"][0]["tool_use_id"] == "t1"
    assert tool_msg["content"][0]["is_error"] is False
    assert client.requests[0]["fallbacks"] == "default"


def test_agent_flags_tool_errors_to_the_model():
    client = FakeClient(
        SimpleNamespace(stop_reason="tool_use", content=[
            tool_use("t1", "query_fleet_db", {"sql": "DROP TABLE vehicles"})]),
        SimpleNamespace(stop_reason="end_turn", content=[text("I can only read data.")]),
    )
    FleetOpsAgent(client=client, model="claude-opus-5-5").run("Delete everything")
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_agent_handles_refusal_and_truncation():
    refusal = FakeClient(SimpleNamespace(stop_reason="refusal", content=[]))
    assert "declined" in FleetOpsAgent(client=refusal, model="m").run("x")["reply"]
    cut = FakeClient(SimpleNamespace(stop_reason="max_tokens", content=[text("Partial")]))
    assert "cut off" in FleetOpsAgent(client=cut, model="m").run("x")["reply"]
