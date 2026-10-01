"""Shared in-memory state: audit trail + human-in-the-loop approval queue.

An in-memory store is enough for a demo; in a real deployment this would be a
table, but the point being demonstrated (agent proposes writes, a human
approves them, every step is logged) doesn't depend on where it's persisted.
"""
from __future__ import annotations

import itertools
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "data" / "fleet.db"

_approval_ids = itertools.count(1)
AUDIT_LOG: list[dict[str, Any]] = []
PENDING_APPROVALS: dict[int, dict[str, Any]] = {}


SEVERITIES = {"low", "medium", "high"}
MAX_ALERT_LENGTH = 500


def get_db(read_only: bool = False) -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} not found: run `python ingestion/build_ontology.py`")
    if read_only:
        # Enforced by SQLite itself: any write on this connection fails.
        conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_event(actor: str, kind: str, detail: dict[str, Any]) -> None:
    AUDIT_LOG.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "kind": kind,
            "detail": detail,
        }
    )


def propose_alert(vehicle_id: str, message: str, severity: str) -> dict[str, Any]:
    # Validated here, not only in the tool schema: the model's tool input is untrusted.
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(SEVERITIES)}")
    message = message.strip()
    if not message or len(message) > MAX_ALERT_LENGTH:
        raise ValueError(f"message must be 1-{MAX_ALERT_LENGTH} characters")
    conn = get_db(read_only=True)
    try:
        known = conn.execute("SELECT 1 FROM vehicles WHERE vehicle_id = ?", (vehicle_id,)).fetchone()
    finally:
        conn.close()
    if not known:
        raise ValueError(f"Unknown vehicle {vehicle_id!r}")

    approval_id = next(_approval_ids)
    entry = {
        "id": approval_id,
        "vehicle_id": vehicle_id,
        "message": message,
        "severity": severity,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    PENDING_APPROVALS[approval_id] = entry
    log_event("agent", "propose_alert", entry)
    return entry


def list_pending() -> list[dict[str, Any]]:
    return [a for a in PENDING_APPROVALS.values() if a["status"] == "pending"]


def decide_approval(approval_id: int, approve: bool, actor: str = "human") -> dict[str, Any]:
    entry = PENDING_APPROVALS.get(approval_id)
    if entry is None:
        raise KeyError(f"No pending approval with id {approval_id}")
    if entry["status"] != "pending":
        raise ValueError(f"Approval {approval_id} already {entry['status']}")

    entry["status"] = "approved" if approve else "rejected"
    log_event(actor, "decide_approval", entry)

    if approve:
        conn = get_db()
        conn.execute(
            "INSERT INTO alerts (vehicle_id, message, severity, created_at) VALUES (?, ?, ?, ?)",
            (entry["vehicle_id"], entry["message"], entry["severity"], entry["created_at"]),
        )
        conn.commit()
        conn.close()
    return entry
