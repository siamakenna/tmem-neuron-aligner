"""Read-only full-plate audit; never executes microscopy processing."""

import argparse
import csv
from pathlib import Path

from tmem_align.audit_v1.full_plate import (
    audit_run,
    load_contract,
    plain,
    private_output,
    sha,
    write_json,
)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--dataset-config", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--process-status", choices=["RUNNING", "EXITED", "UNKNOWN"], default="UNKNOWN")
    a = p.parse_args()
    config = plain(a.dataset_config)
    config_sha = sha(config)
    report = audit_run(a.run_dir, load_contract(config), a.process_status)
    if sha(config) != config_sha:
        raise ValueError("Dataset config changed during audit")
    report["dataset_config_sha256"] = config_sha
    out = private_output(a.out, [a.run_dir, config])
    outputs = {}
    for key in ("by_well", "by_day"):
        path = out / (key + ".csv")
        rows = report[key]
        with path.open("x", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        path.chmod(0o600)
        outputs[path.name] = sha(path)
    report["summary_output_sha256"] = outputs
    write_json(out / "run_audit.json", report)
    print(report["status"])


if __name__ == "__main__":
    main()
