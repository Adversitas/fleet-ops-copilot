"""FastAPI backend for the Fleet Ops Copilot demo.

Run: uvicorn api.main:app --reload
Then open http://127.0.0.1:8000/
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import settings  # noqa: F401  (loads .env before anything reads the environment)
import store
from agent.agent import FleetOpsAgent

app = FastAPI(title="Fleet Ops Copilot")

_agent: FleetOpsAgent | None = None
_conversations: dict[str, list[dict[str, Any]]] = {}

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def get_agent() -> FleetOpsAgent:
    global _agent
    if _agent is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise HTTPException(
                status_code=503,
                detail="ANTHROPIC_API_KEY is not set. Add it to .env and restart the server.",
            )
        _agent = FleetOpsAgent()
    return _agent


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "default"


class ApprovalDecision(BaseModel):
    approve: bool


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    history = _conversations.get(req.conversation_id, [])
    agent = get_agent()
    try:
        result = agent.run(req.message, history=history)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _conversations[req.conversation_id] = result["messages"]
    return {"reply": result["reply"], "trace": result["trace"]}


@app.get("/api/approvals")
def approvals() -> list[dict[str, Any]]:
    return store.list_pending()


@app.post("/api/approvals/{approval_id}")
def decide(approval_id: int, decision: ApprovalDecision) -> dict[str, Any]:
    try:
        return store.decide_approval(approval_id, decision.approve)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/audit-log")
def audit_log() -> list[dict[str, Any]]:
    return store.AUDIT_LOG


@app.get("/api/alerts")
def alerts() -> list[dict[str, Any]]:
    conn = store.get_db()
    try:
        rows = conn.execute("SELECT * FROM alerts ORDER BY alert_id DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")
