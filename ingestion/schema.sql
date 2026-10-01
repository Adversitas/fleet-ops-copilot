-- Normalized "ontology" layer that the agent queries.
-- Raw sources are messy (mixed date formats, free text); this is the clean,
-- unified model an FDE would build on top of a client's real systems.

DROP TABLE IF EXISTS vehicles;
DROP TABLE IF EXISTS drivers;
DROP TABLE IF EXISTS routes;
DROP TABLE IF EXISTS maintenance_logs;
DROP TABLE IF EXISTS driver_notes;
DROP TABLE IF EXISTS alerts;

CREATE TABLE vehicles (
    vehicle_id TEXT PRIMARY KEY,
    make TEXT,
    model TEXT,
    year INTEGER,
    depot_id TEXT
);

CREATE TABLE drivers (
    driver_id TEXT PRIMARY KEY,
    name TEXT,
    depot_id TEXT
);

CREATE TABLE routes (
    route_id TEXT PRIMARY KEY,
    vehicle_id TEXT REFERENCES vehicles(vehicle_id),
    driver_id TEXT REFERENCES drivers(driver_id),
    origin TEXT,
    destination TEXT,
    scheduled_departure TEXT,   -- ISO 8601, normalized at ingest
    scheduled_arrival TEXT,
    actual_departure TEXT,
    actual_arrival TEXT,
    sla_hours REAL,
    status TEXT                 -- computed: on_time | late | at_risk | in_progress
);

CREATE TABLE maintenance_logs (
    log_id TEXT PRIMARY KEY,
    vehicle_id TEXT REFERENCES vehicles(vehicle_id),
    date TEXT,
    issue TEXT,
    severity TEXT,               -- low | medium | high
    resolved INTEGER              -- 0/1
);

CREATE TABLE driver_notes (
    note_id TEXT PRIMARY KEY,
    vehicle_id TEXT REFERENCES vehicles(vehicle_id),
    driver_id TEXT,
    date TEXT,
    text TEXT
);

-- Write actions the agent proposes land here first (human-in-the-loop),
-- and only get applied to `alerts` once approved via the API.
CREATE TABLE alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT,
    message TEXT,
    severity TEXT,
    created_at TEXT
);
