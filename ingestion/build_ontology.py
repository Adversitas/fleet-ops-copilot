"""Builds the unified fleet.db from messy raw sources.

Real client data never arrives clean. This module intentionally deals with:
- mixed date formats across routes.csv rows (ISO vs. US slash format)
- a JSON source (maintenance_logs.json) alongside CSVs
- free-text driver notes (.txt files, standing in for OCR'd PDFs)

Run: python ingestion/build_ontology.py
"""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "fleet.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

DATE_FORMATS = ["%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M"]


def normalize_datetime(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized datetime format: {raw!r}")


def compute_status(sched_arrival: str | None, actual_arrival: str | None, actual_departure: str | None) -> str:
    now = datetime(2026, 9, 8, 10, 0)  # fixed "now" so the demo is reproducible
    if actual_arrival:
        sched = datetime.fromisoformat(sched_arrival)
        actual = datetime.fromisoformat(actual_arrival)
        return "late" if actual > sched else "on_time"
    if not actual_departure:
        return "not_departed"
    sched = datetime.fromisoformat(sched_arrival)
    if now > sched:
        return "late"
    # at risk if less than 1 hour of buffer left before scheduled arrival
    if (sched - now).total_seconds() < 3600:
        return "at_risk"
    return "in_progress"


def build() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    with open(RAW / "vehicles.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        conn.executemany(
            "INSERT INTO vehicles VALUES (:vehicle_id, :make, :model, :year, :depot_id)",
            rows,
        )

    with open(RAW / "drivers.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        conn.executemany(
            "INSERT INTO drivers VALUES (:driver_id, :name, :depot_id)", rows
        )

    with open(RAW / "routes.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sched_dep = normalize_datetime(row["scheduled_departure"])
            sched_arr = normalize_datetime(row["scheduled_arrival"])
            act_dep = normalize_datetime(row["actual_departure"])
            act_arr = normalize_datetime(row["actual_arrival"])
            status = compute_status(sched_arr, act_arr, act_dep)
            conn.execute(
                """INSERT INTO routes
                   (route_id, vehicle_id, driver_id, origin, destination,
                    scheduled_departure, scheduled_arrival, actual_departure,
                    actual_arrival, sla_hours, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["route_id"], row["vehicle_id"], row["driver_id"],
                    row["origin"], row["destination"], sched_dep, sched_arr,
                    act_dep, act_arr, float(row["sla_hours"]), status,
                ),
            )

    with open(RAW / "maintenance_logs.json", encoding="utf-8") as f:
        logs = json.load(f)
        conn.executemany(
            """INSERT INTO maintenance_logs VALUES
               (:log_id, :vehicle_id, :date, :issue, :severity, :resolved)""",
            [{**log, "resolved": int(log["resolved"])} for log in logs],
        )

    note_id = 1
    for path in sorted((RAW / "driver_notes").glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        vehicle_id = path.stem.split("_")[0]
        driver_line = next((l for l in text.splitlines() if l.startswith("Driver:")), "")
        driver_id = driver_line.split("(")[-1].rstrip(")") if "(" in driver_line else None
        date_line = next((l for l in text.splitlines() if l.startswith("Date:")), "")
        date = date_line.replace("Date:", "").strip() or None
        conn.execute(
            "INSERT INTO driver_notes VALUES (?, ?, ?, ?, ?)",
            (f"N-{note_id:02d}", vehicle_id, driver_id, date, text),
        )
        note_id += 1

    conn.commit()

    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ["vehicles", "drivers", "routes", "maintenance_logs", "driver_notes"]
    }
    conn.close()
    print(f"Built {DB_PATH} -> {counts}")


if __name__ == "__main__":
    build()
