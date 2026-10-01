"""Claude tool-use agent loop for the Fleet Ops Copilot.

This is the reusable core: given a user message (and prior turns), it drives
Claude through as many tool calls as it needs, executes them locally via
agent.tools, and returns the final text reply plus the full step trace.

A manual loop (rather than the SDK's tool runner) is used on purpose: every tool
call is recorded in a trace that the UI shows next to the answer.
"""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

import settings
from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOL_SPECS, execute_tool

MAX_TOOL_ROUNDS = 8

# Models that accept server-side refusal fallback: if a safety classifier declines a
# request, the API retries it on a suitable fallback model within the same call.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class FleetOpsAgent:
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 client: Any | None = None) -> None:
        # `client` lets tests inject a fake; normally the real SDK client is used.
        self.client = client or anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        self.model = model or settings.MODEL

    def _create(self, messages: list[dict[str, Any]]) -> Any:
        kwargs: dict[str, Any] = {}
        if "haiku" not in self.model:
            kwargs["output_config"] = {"effort": settings.EFFORT}
        if self.model in _FALLBACK_MODELS:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=settings.MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_SPECS,
            messages=messages,
            **kwargs,
        )

    def run(self, message: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        messages: list[dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": message})
        trace: list[dict[str, Any]] = []

        for _ in range(MAX_TOOL_ROUNDS):
            response = self._create(messages)
            # The full content (including any thinking blocks) goes back unchanged.
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                reply = "The model declined to answer this request."
                return {"reply": reply, "messages": messages, "trace": trace}

            if response.stop_reason != "tool_use":
                reply = "".join(b.text for b in response.content if b.type == "text")
                if response.stop_reason == "max_tokens":
                    reply += "\n\n[Answer cut off: the response hit the token limit.]"
                return {"reply": reply, "messages": messages, "trace": trace}

            # All tool results go back in a single user message.
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = execute_tool(block.name, block.input)
                trace.append({"tool": block.name, "input": block.input, "result": result})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                        "is_error": isinstance(result, dict) and "error" in result,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        return {
            "reply": "Stopped after too many tool-call rounds without a final answer.",
            "messages": messages,
            "trace": trace,
        }
