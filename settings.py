"""Settings shared by the API, the agent and the evals.

Importing this module loads `.env` (if present) into the environment, so every entry
point -- `uvicorn api.main:app`, `python evals/run_evals.py`, the tests -- sees the same
configuration.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader: KEY=value lines; real environment variables take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

MODEL = os.environ.get("FLEET_COPILOT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("FLEET_COPILOT_EFFORT", "medium")  # low | medium | high | xhigh | max
MAX_TOKENS = 16000
