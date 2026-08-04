# Branch strategy

## `main`
Production branch. Only updated via merged PRs from `csp-dev`.

## `csp-dev`
Local integration branch. All feature work merges here first for testing before opening a PR to `main`.

## `gh-pages`
Orphan branch serving the generated TMEM106B review dashboard (HTML/PNG/CSS/JS). Built by `scripts/build_github_pages_dashboard.py`. Not merged from or into any other branch.

## `feature/260213-pilot`
Original pilot analysis branch (fully merged to `main`, no longer active).

## Naming

Feature branches use the `feat/` prefix with a descriptive slug: `feat/roi-export`, `feat/batch-qc-report`, etc.

## Workflow

```
feat/descriptive-name ──→ csp-dev (integrate + test) ──→ PR ──→ main
```

- Unit tests and edge-case tests for a feature are written and passing on the `feat/` branch before merging to `csp-dev`.
- `csp-dev` is for integration testing across features, not for writing new unit tests.
