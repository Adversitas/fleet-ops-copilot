# Architecture

```
raw sources (messy, multi-format)
  data/raw/*.csv, *.json, driver_notes/*.txt
        |
        v
ingestion/build_ontology.py    -- normalizes dates, joins sources, computes
        |                          derived fields (route status)
        v
data/fleet.db (SQLite)         -- the "ontology": one clean queryable model
        |
        v
agent/tools.py                 -- typed tool surface over the ontology:
        |                          3 read tools + 1 write tool (propose_alert)
        v
agent/agent.py                 -- Claude tool-use loop (agent/prompts.py for
        |                          the system prompt / guardrails)
        v
api/main.py (FastAPI)          -- /api/chat, /api/approvals, /api/audit-log
        |
        v
ui/index.html                  -- chat + pending-approvals + audit-log panels
```

## Why this shape

This mirrors what a forward deployed engineer actually builds on a client
engagement, compressed into a runnable demo:

- **Ingestion is the hard part, not the model.** Real client data is never
  one clean table. `build_ontology.py` normalizes two different datetime
  formats and joins a CSV, a JSON export, and free-text notes into one
  schema the agent can reason over.
- **The agent only gets tools, never raw DB access.** `query_fleet_db` is
  restricted to `SELECT`. The only way to change anything is
  `propose_alert`, which writes to a pending-approval queue, not the
  `alerts` table directly.
- **Every write requires a human.** `store.decide_approval` is the only
  path that inserts into `alerts`. The agent can be fully wrong and the
  worst case is a bad draft sitting in a queue, not a bad action taken.
- **Everything is logged.** `store.AUDIT_LOG` records every tool call and
  every approval decision, visible live in the UI. A client's ops team
  needs to be able to see exactly what the agent looked at and did.
- **Evals check tool use, not just text.** `evals/scenarios.yaml` +
  `run_evals.py` assert both that the right tool was called and that the
  answer is grounded -- catching a model that "sounds right" but skipped
  the data.

## Extending this toward a real engagement

- Swap SQLite for the client's actual warehouse/API; `agent/tools.py` is
  the only place that needs to change.
- Swap `search_driver_notes` (LIKE-based) for embeddings/a vector store
  once notes volume grows past keyword matching.
- Swap the in-memory `store.py` state for a real table + auth so approvals
  survive a restart and are attributable to a specific dispatcher.
- Add tracing (OpenTelemetry / a hosted tracer) in place of the plain
  `AUDIT_LOG` list for production observability.
