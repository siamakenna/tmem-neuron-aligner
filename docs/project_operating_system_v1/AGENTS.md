# Agent contract for this project

Read `PROJECT_STATE.md`, `NEXT_TASKS.md`, and `EVIDENCE.md` before work. Inspect repo contents; treat these documents as possibly stale until checked against code.

## Default mission
- Work on **only the highest-priority unblocked task** in `NEXT_TASKS.md`.
- Deliver one small, testable increment, not broad refactoring or unrelated features.
- Preserve existing scientific claims and existing behavior unless the task explicitly changes them.
- Before changes: record reproduction and baseline. After: targeted test, regression check, documented comparison.
- If blocked or two failed approaches: stop, summarize root cause and next diagnostic. Do not keep trying autonomously.
- Update the project ledger and provide files/commit SHA if available. Do not claim success from a green mock score alone.

## Non-negotiable guardrails
- No cost, paid services, license change, public deployment, publication/submission, protected-branch merge, sensitive-data release, or destructive operations without explicit permission.
- Never copy restricted employer/lab data or confidential collaborator work into independent products.
- Don't invent results, users, revenue, benchmark numbers, or approvals.
- If the task is L-size, first split into independently verifiable S/M tasks and perform only the first approved slice.

## Response format
**Result:** [exact diff/deliverable]
**Evidence:** [commands run; count passed/failed/skipped; baseline comparison]
**Unverified:** [what is not verified]
**Next:** [one task, acceptance criteria]
