# 5-Minute Demo Script

1. **Set the scene.** "This is a fleet dispatch copilot. It's wired into the
   customer's route data, maintenance logs, and driver notes -- three
   sources that don't normally talk to each other."

2. **Ask a grounded question.**
   > Which trucks are at risk of missing SLA today, and why?

   Point out the tool trace under the reply -- it queried the live DB, it
   didn't guess.

3. **Show the unstructured-data win.**
   > Is there anything concerning about V-1003 beyond the maintenance log?

   The maintenance log doesn't mention brakes yet -- the driver's free-text
   note does. This is the cross-referencing a client's existing BI tools
   can't do.

4. **Trigger a write action and show the guardrail.**
   > Draft an alert for V-1006 about this morning's no-start / coolant issue.

   The reply says "queued for approval," not "sent." Point at the Pending
   Approvals panel -- nothing happened to real data yet.

5. **Close the loop.** Click Approve. Show the Audit Log entry and that
   `/api/alerts` now has the row. "Every action is attributable and
   reversible before it happens -- that's what makes this deployable in a
   real ops environment, not just a chat demo."

6. **If asked "how do I know it's not making this up":**
   Run `python evals/run_evals.py` -- walk through one assertion that checks
   both the tool call and the grounded answer.
