# Source-only software release verification

The owner explicitly authorized moving qualifying PR #9 out of draft and squash-merging its sanitized final tree. This authorization applies to software infrastructure, not biological classifications or scientific acceptance.

## Fresh verification

- Full repository regression at `2e70f59ce09ba11b715bf337304c9cb6a37f0a9f`: **616 ordinary tests + 135 subtests**, JUnit751, zero failures/errors/skips; 231.77 seconds. One expected warning exercises duplicate ZIP members. No microscope benchmark rerun.
- The existing dependency-complete Python 3.12 environment was reused for that full suite, with explicit PYTHONPATH bound to this source checkout. Its environment/source-binding records and logs are private, outside Git. The smaller portable environment was reused for focused controls; no new production dependency was added.
- Additional UI controller coverage simulates all 108 visits using only synthetic control data: fixed/search image binding, loading disable/clear, timestamp and reviewer attribution, uncertainty notes, private download/reload, stale import rejection and unsaved navigation. No researcher annotation or real review file is filled in.
- The future-panel freezer has focused nonoverlap, determinism, non-overwrite and historical-exclusion tests; it reads master metadata only. The original historical panel reconstructed exactly and its benchmark was not rewritten.
- Publication audit covers the entire sanitized PR tip and staged changes. No credentials, microscopy data, reviewer records, arrays, galleries, environments or detailed logs are intended for main. Public-history exposure remains explicitly documented; squash merging does not erase the original PR branch.

The full suite ran once before the added selection helper and extra UI tests; focused checks cover those additions afterward. Shared preprocessing/registration/measurement code remained unchanged by the final additions. Actual final focused counts and merge receipts are retained in the private execution checkpoint.

## Merge and post-merge checks

Use a squash merge of the verified head, verify the merged PR state and merge SHA, then update a correctly based local main with ff-only pull. Preserve the imported source-base branch rather than discarding a divergent local pointer. Smoke-test merged CLI help, frozen selection and blank source-binding validation; preserve prior outputs with new log/report filenames.

No independent biological review has happened: 108 decisions remain, 17 failed automated visits remain, six tracks are diagnostic rejections and six pending independent review; zero accepted tracks. Browser automation of local-file pages remains unavailable under tool policy; Node state tests are not described as rendered-browser tests.

Next source development belongs on a separate branch and must reconcile genuine private review evidence with the existing v6/export/analysis gates without translating diagnostic decisions into MANUAL_ACCEPTED, computing treatment effects, inventing fate/censoring evidence, or generating real figures from unapproved measurements.
