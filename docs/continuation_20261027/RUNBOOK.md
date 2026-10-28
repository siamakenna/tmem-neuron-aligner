# Local review runbook

The transferred dataset, completed benchmark, environment and original gallery are already available. Do not restart the earlier cluster-connected setup/transfer launcher.

See [REVIEW_VALIDATION_README.md](REVIEW_VALIDATION_README.md) for the offline workspace and private validator commands. Only source preparation, human review and focused code checks are needed now.

The legacy transfer utilities remain available for explicitly configured use on other institutions/devices. They no longer contain a personal username, source directory, cluster host or environment path. Remote operation requires TMEM_REMOTE_USER, TMEM_COMPUTE_HOST, TMEM_REMOTE_ROOT, TMEM_REMOTE_PYTHON and, for data transfer, TMEM_TRANSFER_HOST, TMEM_SOURCE_MASTER, TMEM_SOURCE_ROOTS and TMEM_PRIOR_RUN. Allowed source roots are explicit. Missing configuration fails rather than guessing a private path.

Local verify mode does not need these variables or any remote connection. Remote inventory accepts repeated --source-root arguments and --master. Detailed session state, source paths, environment records, logs and case summaries stay private; only a deliberately minimal aggregate is eligible for legacy result publication.

Environments named .venv* and private directories are excluded from transfer packaging. Generated/local review records are ignored by Git and the publication auditor rejects private/generated artifacts. A Git ignore rule alone is not a privacy review: inspect the full staged/PR diff before pushing.
