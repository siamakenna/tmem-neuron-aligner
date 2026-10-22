#!/usr/bin/env python3
"""Build an immutable portable source, evidence and independent-review packet."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile


SOURCE_SUFFIXES = {'.py', '.sh', '.js', '.json', '.csv', '.md', '.yaml', '.yml', '.toml', '.html', '.txt'}
PAYLOAD_SUFFIXES = SOURCE_SUFFIXES | {'.png', '.jpg', '.jpeg', '.npz', '.npy', '.xml', '.log', '.pptx', '.pdf'}
PINNED_DISTRIBUTIONS = ('numpy', 'scipy', 'scikit-image', 'tifffile', 'nd2', 'pytest',
                        'Pillow', 'pandas', 'matplotlib', 'imageio')
SKIP_PARTS = {'__pycache__', '.pytest_cache', '.git', '.venv'}
MAX_FILE_BYTES = 128 * 1024**2
MAX_TOTAL_BYTES = 500 * 1024**2


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024**2), b''):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def copy_payload_tree(source: Path, destination: Path, suffixes=PAYLOAD_SUFFIXES) -> None:
    """Copy small regular files, rejecting links and large microscopy inputs."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f'Require a regular directory: {source}')
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if any(part in SKIP_PARTS or part.endswith('.egg-info') for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f'Symlinks are not portable handoff evidence: {relative}')
        if not path.is_file() or (path.suffix.lower() not in suffixes and path.name != 'SHA256SUMS'):
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f'Use compact evidence rather than a large input: {relative}')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def environment_record() -> dict:
    versions = {name: importlib.metadata.version(name) for name in PINNED_DISTRIBUTIONS}
    freeze = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True,
                            text=True, check=True).stdout
    return {'python_version': sys.version, 'python_executable': sys.executable,
            'platform': platform.platform(), 'machine': platform.machine(),
            'top_level_versions': versions, 'pip_freeze': freeze,
            'scope': 'Builder environment. The full freeze is a provenance record, '
                     'not a cross-platform dependency lock.'}


def git_record(repo: Path) -> dict:
    """Do not mistake an unrelated ancestor checkout for this source snapshot."""
    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                              text=True, check=False)
    try:
        top = git('rev-parse', '--show-toplevel')
        if top.returncode or Path(top.stdout.strip()).resolve() != repo.resolve():
            return {'kind': 'source_snapshot', 'git_checkout': False}
        commit, state = git('rev-parse', 'HEAD'), git('status', '--short')
    except OSError:
        return {'kind': 'source_snapshot', 'git_checkout': False}
    return {'kind': 'git_worktree_snapshot', 'git_checkout': True,
            'base_commit': commit.stdout.strip(), 'working_tree_status': state.stdout,
            'exact_identity': 'Use included_source_sha256; the base commit alone does not identify modifications.'}


def fresh_stress_results(source: Path, destination: Path) -> None:
    with source.open(newline='') as handle:
        reader = csv.DictReader(handle)
        fields, rows = list(reader.fieldnames or []), list(reader)
    if not fields or 'case' not in fields:
        raise ValueError('Stress matrix requires a case column')
    for row in rows:
        for name in ('observed_result', 'reviewer', 'actual_classification',
                     'failure_classification', 'execution_status', 'execution_role',
                     'notes', 'reviewed_at'):
            if name in row:
                row[name] = ''
    with destination.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def verified_input_parity(root: Path, verification_root: Path | None,
                          source_hashes: dict) -> dict:
    """Final reports may be new, but tested source/data/rendered evidence must match."""
    if verification_root is None:
        return {'status': 'not_yet_verified', 'scope': 'Initial candidate build; no current execution supplied.'}
    snapshot_path = Path(verification_root) / 'source_snapshot.json'
    if not snapshot_path.is_file():
        raise ValueError('Current verification requires source_snapshot.json')
    verified = json.loads(snapshot_path.read_text())
    if verified.get('source_sha256') != source_hashes:
        raise ValueError('Packaged source differs from the freshly verified candidate')
    evidence_hashes = {str(p.relative_to(root)): digest(p)
                       for folder in ('review', 'fixtures', 'evidence')
                       for p in sorted((root / folder).rglob('*')) if p.is_file()}
    if verified.get('review_evidence_sha256') != evidence_hashes:
        raise ValueError('Packaged fixtures/review/evidence differ from the freshly verified candidate')
    return {'status': 'same_tested_inputs',
            'verified_candidate_manifest_sha256': verified.get('manifest_sha256'),
            'source_files_compared': len(source_hashes),
            'data_and_rendered_evidence_files_compared': len(evidence_hashes),
            'scope': 'Fresh-extracted candidate with identical source, fixtures, review assets and evidence. '
                     'The final package adds execution reports; its complete final manifest is verified separately.'}


def claire_readme() -> str:
    return '''# TMEM106B independent stress review, v6

Start with [the evidence index](index.html), then [the offline review](review/index.html).
488 alone defines identity, tracking and ROI geometry. Use 561 for phenotype QC
after identity/ROI judgments. J05_N015 and N05_N011 are historical positive
references requiring renewed review. F05_N025 remains a known exclusion.
All three examples come from TMEM106B wells and cannot establish a matched
control comparison. No human reviews or independent stress results are prefilled.

## 1. Check the fresh extraction

Open a Terminal in this extracted folder. Use Python 3.11 on a suitable analysis
computer or allocated Biowulf node. Keep environments and outputs outside the
immutable package. The verification runner works without Git metadata.

```bash
test -f CLAIRE_README.md
tmem_handoff="$PWD"
tmem_claire_run="$(mktemp -d "$(dirname "$tmem_handoff")/claire_run_XXXXXXXX")"
python3.11 source/scripts/run_claire_verification.py \\
  --handoff-root "$tmem_handoff" \\
  --out "$tmem_claire_run/preflight" --verify-only
```

Preflight must confirm matching SHA256s. Missing or modified evidence is a
failure. Keep the original package unchanged and make experiments in a separate
copy. On Biowulf, first load `python/3.11` and use `python` where these commands
say `python3.11`. Run the full checks on an allocated compute node.

## 2. Create an environment and run all checks

Continue in the same Terminal after successful preflight:

```bash
python3.11 -m venv "$tmem_claire_run/venv"
source "$tmem_claire_run/venv/bin/activate"
python -m pip install -r "$tmem_handoff/requirements_claire.txt" \\
  -e "$tmem_handoff/source"
python "$tmem_handoff/source/scripts/run_claire_verification.py" \\
  --handoff-root "$tmem_handoff" \\
  --out "$tmem_claire_run/verification"
```

The runner records Python/platform/dependencies/source, runs the entire current
test suite, generates synthetic stage PNGs/JSON, exercises the production
alignment/segmentation/phenotype functions on nine known synthetic challenges,
rechecks five small historical IC patches, and checks rejection of pending
review. Detector/QC misses are recorded observations. Unexpected software errors
fail the run. For pending review, exit 2 and no accepted metrics CSV are expected.
Inspect `status.json`, `all_tests.log/xml`, `synthetic/`, `production_stress/`,
`pending_export_check/`, and `stress_execution.csv` in the new output. The runner
records the optional UI DOM test skip when Node is absent. Scientific and mapped
assertion skips remain failures.

Top-level pins describe tested package versions. The builder's full freeze and
platform record are in `provenance/environment.txt` and `environment.json`.
The freeze is a record rather than a cross-platform lock. Your verification
records the actual environment independently.

## 3. Review all nine visits

Inspect 488 identity and ROI purity before unlocking 561. Check adaptive masks,
consensus/core/ROI geometry, stage diagnostics, LUT ranges and clipping counts.
Leave unresolved judgments as `not_reviewed`. Use your actual reviewer name.
Save partial JSON before closing and use Resume to continue. Save the final
`manual_review.json` outside this package, for example in the run directory.
Fresh v6 reviews bind to the exact source evidence, displayed assets and render
configuration. Old v1 approvals cannot approve this workspace. Do not overwrite
the supplied `manual_review_template.json`, manifest, or binding files.

For N05_N011, examine Day 12's adjacent 488 structure and Day 39's weaker signal.
F05_N025 remains excluded despite the old automated soma-screen PASS. Historical
reference labels do not replace your own inspection.

## 4. Execute stress recipes and record outcomes

`stress_results.csv` maps each case to a fixture, command/test, expected outcome
and diagnostic artifact. First copy it outside the immutable package:

```bash
cp "$tmem_handoff/stress_results.csv" "$tmem_claire_run/stress_results.csv"
```

Fill that copy after executing cases. Keep supplied observation/reviewer cells
blank until executed. Use each recipe's stated working directory and new output
paths. Do not edit the original supplied sheet in the package.

The automatic run already exercises all nine synthetic challenges. The individual
production commands in the sheet rerun a named case in a new run directory.
Artifact paths beginning `synthetic/`, `stress_examples/` or `production_stress/`
refer to the verification output. Paths beginning `fixtures/`, `review/` or
`evidence/` refer to the supplied package. Inspect and classify the measured
responses as well as fixture truth. A detector miss is not a software PASS for
scientific accuracy.

Automated `python -m pytest tests/...` recipes run from the packaged source
directory. Enter it before copying a test command from the sheet:

```bash
cd "$tmem_handoff/source"
```

Manual `review/index.html` paths are relative to the handoff root. Blocked cases
need their stated real inputs and cannot be completed by opening a crop alone.

Classify actual failures as `expected_handled`, `new_bug`, `new_QC_condition`,
`scientific_limitation`, or `visualization_only_issue`. Cases marked
`blocked_missing_real_input` cannot be completed with this packet and do not
count as passes. Synthetic tile checks do not verify original microscope
orientation, stitching seams, or acquisition calibration.

## 5. Check export after scientific review

From this handoff root, after saving your JSON in the run directory:

```bash
cd "$tmem_handoff"
python source/scripts/export_reviewed_metrics.py \\
  --curated fixtures --reviews "$tmem_claire_run/manual_review.json" \\
  --config source/configs/tmem_review_v6.json --workspace review \\
  --out "$tmem_claire_run/accepted_review_export"
```

Use a new output directory. Pending, failed, stale, altered, or known-excluded
evidence must produce no accepted metrics. Exit 2 is the expected blocked verdict
when no track qualifies. Accepted rows retain existing quantitative values.
LUTs and display clipping never select or change the measurement ROI.

## Return these results

Return `manual_review.json`, the completed `stress_results.csv`, and the full
verification output folder, including failure diagnostics and `status.json`.
For blocked cases record the missing input and reason. Keep the original package.

Final biological inference requires validated neurons across all three matched
well pairs. Punctate/diffuse mCherry is a computational phenotype decomposition
and does not establish rupture or another specific mechanism.
'''


def index_html(evidence_present: bool, verification_present: bool, stage_links=()) -> str:
    evidence = ('<li><a href="evidence/index.html">Real-data evidence and working slideshow</a></li>'
                if evidence_present else '<li>Real-data evidence is unavailable in this build.</li>')
    verification = ('<li><a href="verification/all_tests.log">Current build test log</a> '
                    'and <a href="verification/all_tests.xml">JUnit results</a></li>'
                    if verification_present else '<li>Current test reports are unavailable in this build.</li>')
    verification += ''.join(f'<li><a href="verification/{path}">{label}</a></li>'
                            for path, label in stage_links)
    return '''<!doctype html><meta charset="utf-8"><title>TMEM106B evidence index</title>
<style>body{font:18px system-ui;max-width:1050px;margin:40px auto;padding:0 24px;color:#142e34}
a{color:#006c72}li{margin:14px 0}p{line-height:1.5}</style>
<h1>TMEM106B independent review and stress evidence</h1>
<p>488 defines identity, tracking and ROI geometry. Use 561 for phenotype QC
afterward. Human acceptance and independent stress judgments remain pending.</p><ul>
<li><a href="CLAIRE_README.md">Step-by-step verification and return instructions</a></li>
<li><a href="review/index.html">488-first offline neuron review</a></li>
''' + evidence + verification + '''
<li><a href="stress_results.csv">Case recipes and blank outcome sheet</a></li>
<li><a href="provenance/source_snapshot.json">Exact packaged source identity</a></li>
<li><a href="provenance/environment.json">Builder environment</a></li>
<li><a href="source/docs/audit_v1/IMPLEMENTATION.md">Current processing scope</a></li>
</ul><p>Three examples do not form a validated six-well cohort. F05_N025 remains
excluded. Missing original tiles and calibration evidence remain explicit limits.</p>
'''


def build_handoff(repo: Path, curated: Path, workspace: Path, out: Path, *,
                  evidence_root: Path | None = None,
                  verification_root: Path | None = None,
                  source_install: Path | None = None,
                  environment: dict | None = None) -> dict:
    repo, curated, workspace, out = map(Path, (repo, curated, workspace, out))
    if out.exists():
        raise FileExistsError(f'Output already exists: {out}')
    config = json.loads((repo / 'configs/tmem_review_v6.json').read_text())
    ids = config['neuron_ids']
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Require distinct review candidates')
    if not (workspace / 'review/index.html').is_file():
        raise ValueError('Require a built review workspace')
    environment = environment if environment is not None else environment_record()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='claire_v6_', dir=out.parent) as temp:
        root = Path(temp)
        source = root / 'source'
        for name in ('src', 'scripts', 'tests', 'configs', 'docs/audit_v1'):
            copy_payload_tree(repo / name, source / name, SOURCE_SUFFIXES)
        for name in ('pyproject.toml', 'README.md'):
            shutil.copyfile(repo / name, source / name)
        for nid in ids:
            copy_payload_tree(curated / nid, root / 'fixtures' / nid)
        copy_payload_tree(workspace / 'review', root / 'review')
        selected_evidence = workspace / 'evidence'
        if not selected_evidence.is_dir():
            selected_evidence = Path(evidence_root) if evidence_root is not None else None
        evidence_present = selected_evidence is not None and selected_evidence.is_dir()
        if evidence_present:
            copy_payload_tree(selected_evidence, root / 'evidence')
            if not (root / 'evidence/index.html').is_file():
                raise ValueError('Included evidence requires index.html')
        verification_present = verification_root is not None
        if verification_present:
            copy_payload_tree(Path(verification_root), root / 'verification')
            for name in ('all_tests.log', 'all_tests.xml'):
                if not (root / 'verification' / name).is_file():
                    raise ValueError(f'Current verification is missing {name}')
        current_install = Path(source_install) if source_install is not None else None
        if current_install is None and verification_root is not None:
            candidate = Path(verification_root) / 'source_install.json'
            current_install = candidate if candidate.is_file() else None
        if current_install is not None:
            (root / 'provenance').mkdir(exist_ok=True)
            shutil.copyfile(current_install, root / 'provenance/current_source_install.json')
        fresh_stress_results(repo / 'docs/audit_v1/claire_stress_cases.csv', root / 'stress_results.csv')
        write_json(root / 'provenance/environment.json', {k: v for k, v in environment.items() if k != 'pip_freeze'})
        (root / 'provenance/environment.txt').write_text(environment['pip_freeze'])
        versions = environment['top_level_versions']
        (root / 'requirements_claire.txt').write_text(''.join(f'{n}=={versions[n]}\n' for n in PINNED_DISTRIBUTIONS))
        source_hashes = {str(p.relative_to(root)): digest(p) for p in sorted(source.rglob('*')) if p.is_file()}
        parity = verified_input_parity(root, verification_root, source_hashes)
        provenance = {'schema_version': 'tmem.claire_handoff.v6', 'source': git_record(repo),
                      'included_source_sha256': source_hashes,
                      'current_source_install_included': current_install is not None,
                      'real_evidence_included': evidence_present,
                      'current_verification_included': verification_present,
                      'verification_scope': parity,
                      'manual_review': 'PENDING', 'independent_stress_review': 'PENDING',
                      'known_exclusions': config.get('known_exclusions', {}),
                      'cohort': ids, 'biological_inference_approved': False}
        write_json(root / 'provenance/source_snapshot.json', provenance)
        (root / 'CLAIRE_README.md').write_text(claire_readme())
        candidate_links = [
            ('status.json', 'Current verification status and test counts'),
            ('case_mapping.json', 'Executed assertions for each stress case'),
            ('synthetic/01_preprocessing/slides.html', 'Synthetic preprocessing and IC stages'),
            ('synthetic/02_alignment/slides.html', 'Synthetic alignment stages'),
            ('synthetic/03_phenotype/slides.html', 'Synthetic phenotype stages'),
            ('synthetic/05_stitching/slides.html', 'Synthetic tile assembly stages'),
            ('stress_examples/index.html', 'Synthetic challenge construction and truth'),
            ('production_stress/index.html', 'Measured production responses to challenge inputs'),
            ('historical_ic_fixture_checks.json', 'Historical real IC patch numerical rechecks'),
        ]
        links = [(name, label) for name, label in candidate_links
                 if (root / 'verification' / name).is_file()]
        (root / 'index.html').write_text(index_html(evidence_present, verification_present, links))
        files = sorted(p for p in root.rglob('*') if p.is_file())
        if sum(p.stat().st_size for p in files) > MAX_TOTAL_BYTES:
            raise ValueError('Handoff exceeds compact-evidence size limit')
        (root / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.relative_to(root)}\n' for p in files))
        with zipfile.ZipFile(out, 'x', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(root)))
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'curated', 'workspace', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('evidence-root', 'verification-root', 'source-install'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    build_handoff(args.repo, args.curated, args.workspace, args.out,
                  evidence_root=args.evidence_root, verification_root=args.verification_root,
                  source_install=args.source_install)
    print(args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
