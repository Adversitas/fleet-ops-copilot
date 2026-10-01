"""Eval harness: runs each scenario through the real agent and checks that it
used the right tools and gave a grounded answer -- not just a plausible one.

Run: python evals/run_evals.py
Requires ANTHROPIC_API_KEY to be set (loads .env if present).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings  # noqa: F401  (loads .env)
from agent.agent import FleetOpsAgent

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.yaml"


def check_scenario(agent: FleetOpsAgent, scenario: dict) -> dict:
    result = agent.run(scenario["prompt"])
    reply_lower = result["reply"].lower()
    tools_used = {step["tool"] for step in result["trace"]}

    checks = []

    if "expect_tools_any_of" in scenario:
        expected = set(scenario["expect_tools_any_of"])
        checks.append(("used expected tool", bool(tools_used & expected)))

    if "expect_answer_contains_any_of" in scenario:
        expected = scenario["expect_answer_contains_any_of"]
        checks.append(
            ("answer contains expected content", any(s.lower() in reply_lower for s in expected))
        )

    if "expect_answer_excludes_all_of" in scenario:
        forbidden = scenario["expect_answer_excludes_all_of"]
        checks.append(
            ("answer avoids forbidden phrasing", all(s.lower() not in reply_lower for s in forbidden))
        )

    passed = all(ok for _, ok in checks)
    return {
        "id": scenario["id"],
        "passed": passed,
        "checks": checks,
        "reply": result["reply"],
        "tools_used": sorted(tools_used),
    }


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Set it in .env or the environment, then re-run.")
        print("(Ingestion, tools, and the API scaffold all work without it -- only live agent")
        print(" calls, and therefore this eval run, need a key.)")
        return 1

    scenarios = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    agent = FleetOpsAgent()

    results = [check_scenario(agent, s) for s in scenarios]

    print(f"\n{'ID':<32} {'RESULT':<8}")
    print("-" * 42)
    for r in results:
        print(f"{r['id']:<32} {'PASS' if r['passed'] else 'FAIL':<8}")
        for name, ok in r["checks"]:
            print(f"   [{'x' if ok else ' '}] {name}")

    n_passed = sum(r["passed"] for r in results)
    print(f"\n{n_passed}/{len(results)} scenarios passed")
    return 0 if n_passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
