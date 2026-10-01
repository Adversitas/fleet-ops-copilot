"""Tool definitions the agent can call, and their execution.

Three read tools (safe, executed immediately) and one write tool
(propose_alert) that never touches real data directly -- it only queues an
approval. That split is the core FDE safety pattern: the agent can look at
anything, but it can't change anything without a human in the loop.
"""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

import store

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "query_fleet_db",
        "description": (
            "Run a read-only SQL SELECT query against the fleet database. "
            "Tables: vehicles(vehicle_id, make, model, year, depot_id), "
            "drivers(driver_id, name, depot_id), "
            "routes(route_id, vehicle_id, driver_id, origin, destination, "
            "scheduled_departure, scheduled_arrival, actual_departure, "
            "actual_arrival, sla_hours, status), "
            "maintenance_logs(log_id, vehicle_id, date, issue, severity, resolved), "
            "driver_notes(note_id, vehicle_id, driver_id, date, text). "
            "status is one of: on_time, late, at_risk, in_progress, not_departed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single read-only SELECT statement."}
            },
            "required": ["sql"],
        },
    },
    {
        "name": "search_driver_notes",
        "description": (
            "Keyword search over free-text driver notes (radio/logbook entries) "
            "for mentions that structured tables wouldn't capture, e.g. informal "
            "reports of mechanical trouble."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword or phrase to search for."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_weather_risk",
        "description": "Look up today's weather-related delay risk for a route (mock third-party integration).",
        "input_schema": {
            "type": "object",
            "properties": {"route_id": {"type": "string"}},
            "required": ["route_id"],
        },
    },
    {
        "name": "propose_alert",
        "description": (
            "Draft an operational alert about a vehicle for a human dispatcher to review. "
            "This does NOT send anything -- it only queues the alert for approval. "
            "Use this instead of claiming you've alerted or notified anyone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vehicle_id": {"type": "string"},
                "message": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["vehicle_id", "message", "severity"],
        },
    },
]


MAX_ROWS = 200  # keeps a careless query from flooding the model's context


def _query_fleet_db(sql: str) -> Any:
    # Two layers: a cheap check that gives the model a clear error message, and a
    # read-only connection that makes writes impossible even if the check is bypassed.
    stripped = sql.strip().lower()
    if not stripped.startswith(("select", "with")):
        return {"error": "Only SELECT statements are permitted."}
    conn = store.get_db(read_only=True)
    try:
        rows = conn.execute(sql).fetchmany(MAX_ROWS + 1)
        result = [dict(row) for row in rows[:MAX_ROWS]]
        if len(rows) > MAX_ROWS:
            return {"rows": result, "note": f"Truncated to {MAX_ROWS} rows; refine the query."}
        return result
    except sqlite3.Error as exc:  # surfaced back to the model, not raised
        return {"error": str(exc)}
    finally:
        conn.close()


def _search_driver_notes(query: str) -> Any:
    conn = store.get_db(read_only=True)
    try:
        rows = conn.execute(
            "SELECT note_id, vehicle_id, driver_id, date, text FROM driver_notes "
            "WHERE text LIKE ?",
            (f"%{query}%",),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _get_weather_risk(route_id: str) -> Any:
    # Deterministic mock so the demo is reproducible: hash the route id into
    # a risk bucket rather than calling a real weather API.
    digest = hashlib.sha256(route_id.encode()).hexdigest()
    bucket = int(digest, 16) % 3
    risk = ["low", "medium", "high"][bucket]
    reasons = {
        "low": "Clear conditions along the corridor.",
        "medium": "Scattered storms possible near the destination in the next few hours.",
        "high": "Severe weather advisory active along part of the route.",
    }
    return {"route_id": route_id, "risk": risk, "reason": reasons[risk]}


def _propose_alert(vehicle_id: str, message: str, severity: str) -> Any:
    try:
        entry = store.propose_alert(vehicle_id, message, severity)
    except ValueError as exc:
        return {"error": str(exc)}
    return {
        "queued": True,
        "approval_id": entry["id"],
        "status": "pending_human_approval",
    }


_DISPATCH = {
    "query_fleet_db": lambda i: _query_fleet_db(i["sql"]),
    "search_driver_notes": lambda i: _search_driver_notes(i["query"]),
    "get_weather_risk": lambda i: _get_weather_risk(i["route_id"]),
    "propose_alert": lambda i: _propose_alert(i["vehicle_id"], i["message"], i["severity"]),
}


def execute_tool(name: str, tool_input: dict[str, Any]) -> Any:
    if name not in _DISPATCH:
        return {"error": f"Unknown tool: {name}"}
    result = _DISPATCH[name](tool_input)
    store.log_event("agent", f"tool_call:{name}", {"input": tool_input, "result": result})
    return result
