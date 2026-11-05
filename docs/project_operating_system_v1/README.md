# Lean AI Project Operating System (v1.0)

**Default for research, software, hackathons, portfolios, and application support.**

The objective is to maximize verified, finished work per hour and per paid AI credit. This is a workflow contract, not a demand for more features, tests, or autonomous iterations.

## Operating principles

1. **One source of truth:** the repository/project folder, not an AI chat. Keep `PROJECT_STATE.md`, `NEXT_TASKS.md`, and `EVIDENCE.md` current.
2. **One implementation task at a time:** at most one major active build, one validation/review task, and one small administrative task across concurrent projects. Pause lower-priority work.
3. **Small, testable increments:** a task should normally require 20–60 minutes of focused agent work or one verifiable deliverable. Split work that spans multiple components or deployments.
4. **Proof, not promises:** every completion claim requires a file, diff, passing check, measured metric, or verified URL. Do not equate mock scores with official evaluation.
5. **Minimize handoff cost:** next agent reads the four standardized files, inspects actual code, and does not ask the user to repeat known context.
6. **Default $0 spend:** use existing subscriptions and local tools. Paid inference, deployment, cloud resources, subscriptions, and external payments require permission.
7. **Guard research and privacy:** keep NIH/lab, confidential, collaborator, unpublished, or restricted materials separate from independent commercial or hackathon work. Verify ownership and licenses before reuse.
8. **No hidden publication:** writing and internal testing can proceed; public pushes, merges into protected branches, deployments, application submissions, paid actions, and external outreach need the user's stated authorization and scope.
9. **Choose completion over speculative polish:** the goal is an independently verified release, submission, or scientific result.

## Six-gate lifecycle

| Gate | Required artifact | Exit criterion | Stop/escalate if |
|---|---|---|---|
| G0 — Triage (5–10 min) | 1-sentence objective; deadline; value; effort; constraints | Decide: do / defer / drop | No clear output or deadline/value |
| G1 — Brief (10–15 min) | `PROJECT_STATE.md` and 3 ranked tasks | Scope, permissions, baseline and done criteria explicit | Inputs/rights or data access are uncertain |
| G2 — Implement (1 task) | Feature branch + narrowly scoped diff | One happy path end-to-end works | 2 failed approaches, missing permissions, scope creep |
| G3 — Verify | Targeted tests, edge cases, actual execution, `EVIDENCE.md` | No critical failures, evidence recorded | Same defect after 2 attempts; invented/unavailable evidence |
| G4 — Ship | Minimal docs, demo, release checklist | Deliverable works and approved actions done | Unverified external dependency, privacy/license issue |
| G5 — Archive | Final handoff, issue list, next action | Repo state reproducible and next agent can resume | Key facts only live in chat |

**Sprint loop:** read state → select one task → reproduce/baseline → implement smallest change → run targeted tests → check regression → update evidence/state → commit → stop. No unlimited iterative polishing.

## Choose task size before any agent run

- **S (10–30 min):** single bug/test/doc change. One objective, one acceptance criterion, one short report.
- **M (30–90 min):** single feature across 1–3 components. Explicit acceptance tests and rollback.
- **L (multiple phases):** multiple features, deployment, or scientific analyses. Break into ordered S/M tickets; never send all phases as one autonomous command.

Prefer one Codex/Claude session per S/M ticket. Limit an automated repair cycle to **two attempts** before requiring a diagnostic summary and a new plan. Stop after two rounds of unchanged or worsening *measured* quality; don't invent better scores.

## Daily and weekly cadence

- **Daily (5 minutes):** pick one deliverable, identify the current blocker, set the next acceptance check. If nothing is blocked, don't create extra work.
- **Build block:** one ticket; run relevant tests; write outcome. Avoid hopping repositories mid-run.
- **End of session (3 minutes):** update `PROJECT_STATE.md` + `NEXT_TASKS.md`, record tests and commit SHA. If unfinished, record the exact failure and reproduction command.
- **Weekly (15 minutes):** compare project priorities against fixed deadlines and financial/time budget; archive obsolete initiatives; choose at most one new substantial project.

## Scoring / evaluation policy

1. Freeze the old build and evaluation input before patching.
2. Identify score dimensions, their actual definitions, and which are measurable locally. Separate *judges' official scores*, *internal mock scores*, and *hypotheses*.
3. Fix a demonstrated top contributor to failure, not a speculative feature.
4. Re-evaluate on the same inputs and record variance, regressions, and limitations.
5. If two cycles fail to improve, stop feature churn and investigate rubric mismatch, test noise, or product positioning.
6. Never report simulated user studies as human trials, or fabricated metrics as benchmarks.

## Routing by task

- **ChatGPT chat:** scope, synthesis, scientific review, project prioritization, tests/fixtures, writing and release decisions.
- **Codex:** implementation, repository edits, running tests, precise commits/PRs, reproducible builds.
- **Claude or alternative:** only when a genuinely independent review or model-specific strength is worth the extra usage; provide the same task packet.
- **Work/browser:** only for workflows that require authenticated websites or graphical interactions unavailable to the developer agent. Avoid using Work to merely rewrite a prompt.
- **GitHub:** canonical state. A conversation summary is supplementary and can go stale.

## Escalation and permissions

**Can proceed without another question (if user has requested the work):** read files, edit local branch, prepare new code/tests/docs, run free local checks, draft reports and submissions, create reproducible artifacts.

**Stop for explicit permission:** spending money, public release/deployment/merge unless explicitly authorized, deleting/overwriting data, accessing sensitive accounts, submitting applications/posts, contacting people, exposing NIH or collaborator materials, changing licenses/IP ownership, or making unsupported scientific/financial claims.

**Response contract for every engineering turn:**

1. **Outcome:** what changed, with files and SHA/URL if real.
2. **Evidence:** exact tests and metrics, with pass/fail/skipped and baseline comparison.
3. **Blockers:** only real obstacles (and why).
4. **Next action:** one bounded ticket with acceptance criteria.

No excessive progress narration, generic audit score inflation, or repeat brainstorming when a testable task exists.

## Templates

- `AGENTS.md`: instructions that coding agents read first.
- `PROJECT_STATE.md`: current verified state and blockers.
- `NEXT_TASKS.md`: priority queue (only 3 active).
- `TASK_CARD.md`: copyable one-ticket prompt.
- `EVIDENCE.md`: test and scientific provenance ledger.
- `RELEASE_CHECKLIST.md`: approval and shipping gate.
- `MEMORY_PREFERENCE.txt`: concise wording for ChatGPT's Memory summary.

Copy these into a new repository, fill the brackets, and keep them under version control. Do not blindly commit them over existing agent-specific instructions; reconcile first.
