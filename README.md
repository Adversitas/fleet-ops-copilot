# Fleet Ops Copilot

An AI copilot for a logistics dispatch team. It answers operational questions by querying the
company's data itself, spots problems that only show up when sources are combined, and drafts
alerts, which a **human must approve** before anything happens.

> *"Which trucks are at risk of missing their delivery deadline today, and why?"*
>
> **V-1003** (R-5003, Atlanta → Nashville) is already late: due 09:30 and still on the road.
> **V-1005** (R-5005, Dallas → Houston) is at risk: due 10:30 with under an hour of margin.
> V-1003 also has an unresolved high-severity brake-pad entry, and its driver's note this
> morning says the brakes felt soft. *Tools used: query_fleet_db → search_driver_notes*
>
> <sub>Illustrative answer based on the demo data; wording varies between runs.</sub>

It's built the way a **forward-deployed engineer** works on a client engagement: start from the
customer's messy data, connect an LLM agent to their systems through a small set of safe tools,
and ship something the operations team can actually click on, with evaluations proving the agent
behaves.

All data in this repo is **synthetic**.

---

## How it works

```
 data/raw/  (messy: CSV + JSON + free-text notes, mixed date formats)
     │  ingestion/build_ontology.py
     ▼
 data/fleet.db  (SQLite: one clean, queryable model)
     │
     ▼
 agent/tools.py ── 3 read tools + 1 "write" tool that only queues a draft
     │
     ▼
 agent/agent.py ── Claude tool-use loop: decides which tools to call, reads results, answers
     │
     ▼
 api/main.py (FastAPI) ──► ui/index.html: chat · pending approvals · audit log
```

### 1. Ingestion: turning messy sources into one model

Real client data never arrives as one clean table. Here, the dispatch data lives in:

| Source | Format | Mess |
|---|---|---|
| `vehicles.csv`, `drivers.csv` | CSV | none |
| `routes.csv` | CSV | **two different date formats** (`2026-09-08 06:00` and `09/08/2026 06:00`) |
| `maintenance_logs.json` | JSON export | booleans, a different system |
| `driver_notes/*.txt` | free text | radio/logbook notes, standing in for scanned forms |

`build_ontology.py` normalises every date to ISO 8601, joins all sources into one SQLite schema,
and **computes each route's status** (`on_time`, `late`, `at_risk`, `in_progress`,
`not_departed`) from scheduled vs. actual times. The demo clock is fixed, so results are
reproducible.

### 2. Tools: what the agent is allowed to do

| Tool | What it does | Safety |
|---|---|---|
| `query_fleet_db` | Runs a SQL `SELECT` on the fleet database | Database opened **read-only** at the SQLite level, so writes are impossible even if the text check is bypassed; results capped at 200 rows |
| `search_driver_notes` | Keyword search over free-text notes | Read-only |
| `get_weather_risk` | Weather delay risk for a route | Deterministic mock of a third-party API |
| `propose_alert` | Drafts an alert about a vehicle | **Sends nothing.** Validates its input, then queues the draft for human approval |

The agent never gets raw database access, only these tools. Swapping SQLite for the client's real
warehouse or API means changing `tools.py` and nothing else.

### 3. The agent loop

`agent/agent.py` sends the question to Claude together with the tool definitions. When Claude
asks for a tool, the loop runs it, sends the result back and repeats (up to 8 rounds) until
Claude gives a final answer. Every tool call is recorded in a **trace** that the UI shows under
the answer, so a dispatcher can see *what the answer is based on*.

The system prompt (`agent/prompts.py`) requires answers to be grounded in tool results,
encourages cross-checking structured data against driver notes, and forbids claiming that
anything was "sent". The model can only say an alert was *drafted*.

### 4. Human in the loop

`propose_alert` puts the draft in a pending queue. Only a person clicking **Approve** in the UI
writes it to the `alerts` table (`store.decide_approval`). If the agent is wrong, the worst case
is a bad draft waiting in a queue, not a wrong message sent to a driver. Every tool call and
every decision is written to an **audit log** shown live in the UI.

The UI treats everything the model writes as untrusted and escapes it before display. The agent
reads free-text driver notes, so a malicious note could otherwise smuggle HTML or script into an
alert (prompt injection leading to XSS).

### 5. Evaluations

Two levels:

- **Offline tests** (`tests/`, no API key): date parsing, route status logic, the read-only
  guarantee (`DELETE`, stacked `DROP`, `WITH … DELETE` are all refused), alert validation, the
  approval flow, and the agent loop itself, driven by a scripted fake Claude client.
- **Live agent evals** (`evals/scenarios.yaml`, needs an API key): each scenario checks that the
  agent **used the right tool** and that the answer **contains the facts from the data**. For
  example, it must find the brake issue that appears only in a driver note, must say "queued for
  approval" rather than "sent", and must not invent a status for a vehicle that doesn't exist.

---

## Getting started

### Requirements

- Python 3.10+
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com)). Only needed for
  the live agent; ingestion, tests and the UI run without one.

### Setup

```bash
git clone https://github.com/Adversitas/fleet-ops-copilot.git
cd fleet-ops-copilot
python -m venv .venv
.venv\Scripts\activate                  # Linux / macOS: source .venv/bin/activate
pip install -r requirements-dev.txt

python ingestion/build_ontology.py      # builds data/fleet.db from data/raw/
copy .env.example .env                  # Linux / macOS: cp .env.example .env
```

Open `.env` and set `ANTHROPIC_API_KEY`. Optionally choose the model and effort with
`FLEET_COPILOT_MODEL` (default `claude-opus-5-5`) and `FLEET_COPILOT_EFFORT` (default `medium`).

### Run the app

```bash
uvicorn api.main:app --reload
```

Open **http://127.0.0.1:8000** and try:

1. *"Which trucks are at risk of missing SLA today, and why?"* (watch the tool trace)
2. *"Is there anything concerning about V-1003 beyond the maintenance log?"* (the brake problem
   is only in a driver's note)
3. *"Draft an alert for V-1006 about this morning's no-start issue."* (it appears under
   **Pending approvals**; click **Approve** and see it in the audit log)

[docs/demo_script.md](docs/demo_script.md) has a 5-minute walkthrough.

### Run the tests and evals

```bash
pytest                          # offline, no API key needed
python evals/run_evals.py       # live agent scenarios, uses the API key
```

---

## Project structure

```
data/raw/            synthetic messy source data (CSV, JSON, free-text notes)
ingestion/           build_ontology.py + schema.sql -> data/fleet.db
agent/
  tools.py           tool definitions and their (safe) implementations
  agent.py           Claude tool-use loop with step trace
  prompts.py         system prompt and guardrails
store.py             approval queue, audit log, database access
settings.py          loads .env; model, effort and token settings
api/main.py          FastAPI backend: chat, approvals, audit log, alerts
ui/index.html        chat + pending approvals + audit log front end
evals/               live scenario evals (scenarios.yaml, run_evals.py)
tests/               offline unit tests, including a fake Claude client
docs/                architecture notes and demo script
```

## Taking it toward production

- Replace SQLite with the client's warehouse or API (only `agent/tools.py` changes).
- Replace keyword note search with embeddings once note volume grows.
- Persist the approval queue and audit log in a database, with authentication, so decisions
  survive restarts and are attributable to a named dispatcher.
- Replace the in-memory audit list with proper tracing (e.g. OpenTelemetry).

See [docs/architecture.md](docs/architecture.md) for the design rationale.
