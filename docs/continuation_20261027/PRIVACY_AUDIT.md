# PR #9 privacy and portability audit

Scope: the entire PR tip relative to main, including the original instrumentation and portable additions, plus all newly staged changes. No original images, arrays, galleries, reviewer records, environments or full execution logs are eligible for publication.

## Remediations

- Removed embedded personal cluster usernames, home/source directories, environment IDs and hardcoded host targets from the legacy portable utilities. Remote use now requires explicit configuration; local review and validation require no remote access. Missing configuration fails closed.
- Legacy session publication now emits only a deliberately minimal aggregate rather than detailed state, source paths, environment verification records or case measurements. Private/environment directories and credential-related paths are excluded from packaging.
- Preserved exact original detailed case/audit/local-results receipts and original continuation documents in a private sibling support directory before public sanitization. Public receipt files now contain original SHA256 references and limitations, not per-cell measurements, anchors or private command outputs.
- Moved detailed per-case quantitative and provisional image observations out of public notes. Current private readiness/workspace outputs expose them to the researcher. Public aggregate counts are retained intentionally because the user explicitly supplied them as the checkpoint contract; they are not scientific discoveries.
- Added Git ignore patterns and a tested publication auditor that rejects generated/binary data, review schemas/CSV, nonempty reviewer attribution, obvious credential tokens, private absolute paths and detailed image-derived receipts. Ignore rules do not replace manual diff review.

Run before publication:

```bash
../.venv-local/bin/python scripts/audit_publication.py --staged
```

After committing, audit every changed PR-tip file using the inspected main SHA:

```bash
../.venv-local/bin/python scripts/audit_publication.py \
  --base cbed28cef77826cd8a5b45b6520fa81b127b3bfa
```

No credential-like secret was identified in the reviewed source diff. This is a scoped inspection, not a guarantee that a regex can detect every possible secret. Synthetic test identifiers are software controls, not credentials or real reviewers.

## Important history limitation

The previous public commit already contained the old source paths and detailed receipts. A normal forward cleanup removes them from the current PR tip but **does not erase public Git history, cached diffs or prior downloads**. Original scientific evidence was not falsified or force-rewritten. No force-push/history rewrite or repository-visibility change is performed. Any further history-removal/security response requires an explicit owner decision.

Private originals and new annotations must travel separately from Git. Fingerprints preserve legitimate provenance without needless public disclosure of machine-specific details.
