#!/usr/bin/env python3
"""Release only evidence-bound, fully manually accepted longitudinal metrics."""
import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

from tmem_align.audit_v1.review_gate import (
    evidence_manifest, evaluate_review, review_directory, verify_review_workspace,
)


def portable_git_commit(repo):
    """Use only this checkout's Git metadata; a portable ZIP needs no Git."""
    if not (repo/'.git').exists():
        return 'source_snapshot'
    try:
        top=subprocess.run(['git','-C',str(repo),'rev-parse','--show-toplevel'],
                           capture_output=True,text=True,check=False)
        if top.returncode or Path(top.stdout.strip()).resolve()!=repo.resolve():
            return 'source_snapshot'
        commit=subprocess.run(['git','-C',str(repo),'rev-parse','HEAD'],
                              capture_output=True,text=True,check=False)
    except OSError:
        return 'source_snapshot'
    return commit.stdout.strip() if commit.returncode==0 else 'source_snapshot'


def automated_failures(folder):
    failures=[]
    for filename,fields in [('metrics.csv',['adaptive_valid','single_soma_pass']),
        ('fixture_tracks.csv',['tracking_valid','global_reg_qc_pass','global_reg_well_registration_qc_pass'])]:
        with (folder/filename).open(newline='') as f:rows=list(csv.DictReader(f))
        for r in rows:
            for field in fields:
                if r.get(field,'').strip().lower() not in {'true','1'}:
                    failures.append(f'{filename} day{r.get("day","?")}: {field} is not true')
            if filename=='metrics.csv':
                quantities=['phenotype_roi_area','total_mcherry_intensity',
                    'punctate_mcherry_integrated_intensity','diffuse_mcherry_integrated_intensity','puncta_count']
                values={}
                for field in quantities:
                    try:value=float(r[field])
                    except (KeyError,TypeError,ValueError):value=float('nan')
                    invalid=not math.isfinite(value) or value<0
                    if field=='phenotype_roi_area' and value<=0:invalid=True
                    if field=='puncta_count' and math.isfinite(value) and not value.is_integer():invalid=True
                    if invalid:
                        failures.append(f'metrics.csv day{r.get("day","?")}: invalid {field}')
                    values[field]=value
                if not math.isclose(values['total_mcherry_intensity'],
                    values['punctate_mcherry_integrated_intensity']+values['diffuse_mcherry_integrated_intensity'],
                    rel_tol=1e-6,abs_tol=1e-4):
                    failures.append(f'metrics.csv day{r.get("day","?")}: intensity partition does not conserve total')
    return failures


def export(curated,review_path,config_path,out,*,workspace=None):
    config=json.loads(config_path.read_text());review=json.loads(review_path.read_text())
    manifest=evidence_manifest(curated,config['neuron_ids'])
    if workspace is None:
        raise ValueError('v6 export requires --workspace to verify the exact displayed review evidence')
    review_root=review_directory(workspace)
    if json.loads((review_root/'config.json').read_text()) != config:
        raise ValueError('Export configuration differs from the configuration shown during review')
    rendered=verify_review_workspace(review_root,manifest,config['known_exclusions'])
    result=evaluate_review(review,manifest,config['known_exclusions'],
                           workspace_sha256=rendered['workspace_sha256'])
    result['gate_scope']='Manual review verdict; automated QC is checked separately before metrics export'
    out.mkdir(parents=True,exist_ok=False)
    (out/'review_verdicts.json').write_text(json.dumps(result,indent=2)+'\n')
    if not result['accepted_ids']:
        print('BLOCKED: no fully accepted tracks. No accepted metrics CSV was written.')
        return 2
    invalid={nid:automated_failures(curated/nid) for nid in result['accepted_ids']}
    invalid={nid:reasons for nid,reasons in invalid.items() if reasons}
    if invalid:
        (out/'automated_qc_block.json').write_text(json.dumps(invalid,indent=2)+'\n')
        print('BLOCKED: manually accepted track has failed/missing automated QC. No accepted metrics CSV was written.')
        return 2
    rows=[]
    for nid in result['accepted_ids']:
        with (curated/nid/'metrics.csv').open(newline='') as f:source=list(csv.DictReader(f))
        if len(source)!=9 or [int(r['day']) for r in source]!=[8,12,16,20,25,29,32,36,39]:
            raise ValueError('Accepted track metrics do not contain the nine expected visits')
        for r in source:
            if r['neuron_id']!=nid:raise ValueError('Metric row neuron mismatch')
            rows.append({**r,'source_review_status':r.get('review',''),
                'review':'MANUAL_ACCEPTED','reviewer':review['reviewer'],
                'reviewed_at':review['reviewed_at'],'review_gate_pass':True,
                'evidence_sha256':next(m['evidence_sha256'] for m in manifest if m['neuron_id']==nid)})
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with (out/'accepted_neuron_metrics.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    wells=sorted({r['well'] for r in rows})
    repo=Path(__file__).resolve().parents[1]
    code_files=['scripts/export_reviewed_metrics.py','src/tmem_align/audit_v1/review_gate.py']
    code_hashes={name:hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in code_files}
    (out/'analysis_scope.json').write_text(json.dumps(dict(accepted_ids=result['accepted_ids'],
        wells=wells,biological_pairs=config['biological_pairs'],ic_policy=config['ic_policy'],
        config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        review_file_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
        review_workspace_sha256=rendered['workspace_sha256'],
        render_manifest_sha256=hashlib.sha256((review_root/'render_manifest.json').read_bytes()).hexdigest(),
        export_code_sha256=code_hashes,base_git_commit=portable_git_commit(repo),
        python_version=sys.version,
        inference_ready=False,note='Accepted measurements only. Final matched-pair inference needs '
        'the prespecified cohort and statistical analysis; neurons are not independent biological replicates.'),indent=2)+'\n')
    print(f'Saved {len(rows)} manually accepted neuron-day rows in {out}')
    return 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--curated',type=Path,required=True);p.add_argument('--reviews',type=Path,required=True)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--workspace',type=Path,required=True,
                   help='Exact portable review directory, or workspace parent containing review/')
    a=p.parse_args();return export(a.curated,a.reviews,a.config,a.out,workspace=a.workspace)


if __name__=='__main__':raise SystemExit(main())
