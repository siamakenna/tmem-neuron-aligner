#!/usr/bin/env python3
"""Build offline, evidence-bound review views without changing scientific arrays."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import shutil

import numpy as np

from tmem_align.audit_v1.display import LUT, apply_lut_for_display, make_qc_panel
from tmem_align.audit_v1.display_policy import choose_lut, clipping_stats
from tmem_align.audit_v1.review_gate import evidence_manifest, finalize_review_workspace
from tmem_align.audit_v1.parameters import build_resolved_parameters


def outline(mask):
    padded = np.pad(mask, 1, mode='constant', constant_values=False)
    interior = (padded[:-2, 1:-1] & padded[2:, 1:-1]
                & padded[1:-1, :-2] & padded[1:-1, 2:])
    return mask & ~interior


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def copy_diagnostics(source, target):
    """Copy small artifacts. Original uint16 arrays remain in source fixtures."""
    target.mkdir()
    for name in ['parameters.json', 'segmentation_qc.csv', 'crop_geometry.json',
                 'soma_screen.json', 'luts.json', 'metrics.csv', 'fixture_tracks.csv']:
        file = source / name
        if file.is_file() and not file.is_symlink():
            shutil.copyfile(file, target / name)
    for folder in sorted(source.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        if folder.name != '00_roi' and not folder.name.startswith('day_'):
            continue
        for file in sorted(folder.iterdir()):
            if file.suffix not in {'.png', '.json', '.csv', '.html'}:
                continue
            if file.is_symlink() or not file.is_file():
                raise ValueError('Linked diagnostics must be regular local files')
            dest = target / folder.name / file.name
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(file, dest)


def relative_link(path, root, label):
    return dict(href=str(path.relative_to(root)), label=label)


def links_if_present(folder, root, files):
    return [relative_link(folder / name, root, label)
            for name, label in files if (folder / name).is_file()]


def diagnostic_index(dest, *, neuron_id, groups, identity):
    title = f'{neuron_id}: ' + ('488 identity intermediates' if identity else '561 phenotype intermediates')
    description = ('Geometry and identity use 488 only. Inspect adaptive masks before relying on a fixed consensus core.'
                   if identity else 'Raw 561 is the registered crop before local phenotype background correction. '
                   'These images do not define neuron identity, tracking or ROI geometry.')
    sections = []
    for label, links in groups:
        items = ''.join(f'<li><a href="{html.escape(link["href"], quote=True)}">'
                        f'{html.escape(link["label"])}</a></li>' for link in links)
        sections.append(f'<h2>{html.escape(label)}</h2><ul>{items}</ul>')
    dest.write_text('<!doctype html><meta charset="utf-8"><title>' + html.escape(title)
                    + '</title><style>body{font:17px system-ui;max-width:1000px;margin:32px auto;'
                    'padding:0 20px;line-height:1.5}a{overflow-wrap:anywhere}li{margin:6px 0}</style>'
                    + '<h1>' + html.escape(title) + '</h1><p>' + html.escape(description)
                    + '</p><p><a href="index.html">Return to review</a></p>' + ''.join(sections))


def write_html(path):
    """Static UI shell. Code, data and this HTML enter the render manifest."""
    path.write_text('''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TMEM106B independent neuron review</title>
<style>
body{font:16px system-ui;background:#102127;color:#f4f8f7;margin:0 auto;padding:24px;max-width:1250px;line-height:1.45}
h1,h2,h3{line-height:1.2}p{max-width:80em}section{border:1px solid #49636c;border-radius:8px;padding:20px;margin:28px 0}
.warning{color:#ffd88a}.muted{color:#bdd0d5}.status{font-weight:700;padding:10px 0}.dirty{color:#ffd88a}
label{display:block;margin:10px 0}input,select,textarea,button{font:inherit;padding:7px;max-width:100%;box-sizing:border-box}
input[type=text]{width:340px}textarea{width:100%;min-height:65px}button{cursor:pointer;background:#5ce0ca;color:#102127;border:0;border-radius:4px;margin:8px 6px 8px 0}
button:disabled{opacity:.5;cursor:default}table{border-collapse:collapse;width:100%;font-size:15px}th,td{border:1px solid #49636c;padding:7px;vertical-align:top}
th{text-align:left}.active-day{background:#23444b}.active-day button{outline:2px solid #fff}img{max-width:100%;image-rendering:pixelated;background:#111}
.full{display:block;width:100%;max-width:1100px}a{color:#70ead8;overflow-wrap:anywhere}code{overflow-wrap:anywhere}
.links a{display:inline-block;margin:4px 14px 4px 0}.metadata{font-size:14px;overflow-wrap:anywhere}.visit-notes{margin:16px 0}
.top-controls{border-bottom:1px solid #49636c;padding-bottom:16px}.phenotype-section{margin-top:18px}details{margin:12px 0}
@media(max-width:700px){body{padding:12px}section{padding:12px}table{font-size:12px}th,td{padding:4px}select{max-width:125px}}
</style></head><body>
<h1>TMEM106B: identity, ROI and phenotype review</h1>
<p>Judge neuron identity and ROI purity using <b>488 only</b>. Review 561 phenotype after completing the 488 judgments.
Each view retains the original 128 × 128 geometry. LUTs change display intensity only.</p>
<p class="warning">These historical example tracks do not establish a validated matched control/TMEM106B cohort.
Known exclusions stay enforced. Every candidate requires explicit review across all nine visits.</p>
<div class="top-controls">
<label>Reviewer name <input id="reviewer" type="text" placeholder="Enter your actual reviewer name"></label>
<label>Resume a saved v6 review <input id="load" type="file" accept=".json,application/json"></label>
<p id="save-status" class="status" aria-live="polite">No decisions changed yet. Save a JSON before closing.</p>
<p>Review decisions remain in this page until you download the JSON. Save partial reviews and use Resume to continue.
The export command separately verifies the source data and the exact displayed evidence.</p>
<p id="workspace-scope" class="metadata"></p>
</div>
<div id="tracks"></div>
<button id="save" type="button">Save manual_review.json</button>
<pre id="message" aria-live="polite"></pre>
<p id="global-evidence" class="links"></p>
<script src="review_data.js"></script><script src="review_binding.js"></script><script src="ui.js"></script>
</body></html>\n''')


def build(curated, config_path, out, evidence_root=None):
    curated, config_path, out = Path(curated), Path(config_path), Path(out)
    config = json.loads(config_path.read_text())
    manifest = evidence_manifest(curated, config['neuron_ids'])
    out.mkdir(parents=True, exist_ok=False)
    review = out / 'review'
    review.mkdir()
    if evidence_root is not None:
        evidence_root = Path(evidence_root)
        if not (evidence_root / 'index.html').is_file():
            raise ValueError('The supplied evidence root must contain index.html')
        shutil.copytree(evidence_root, out / 'evidence')
        config['evidence_index'] = '../evidence/index.html'
    else:
        config.pop('evidence_index', None)
    write_json(review / 'config.json', config)
    write_json(review / 'evidence_manifest.json', manifest)
    shutil.copyfile(Path(__file__).with_name('review_ui.js'), review / 'ui.js')
    repo = Path(__file__).resolve().parents[1]
    rows, tracks = [], []
    for item in manifest:
        nid, source = item['neuron_id'], curated / item['neuron_id']
        with np.load(source / 'small_fixture.npz', allow_pickle=False) as fixture:
            boxes, core, roi = fixture['boxes_tcyx'], fixture['identity_core'], fixture['phenotype_roi']
            adaptive, valid = fixture['adaptive_masks'], fixture['adaptive_valid']
        if (boxes.shape != (9, 3, 128, 128) or boxes.dtype != np.uint16
                or core.shape != (128, 128) or roi.shape != core.shape
                or core.dtype != bool or roi.dtype != bool
                or adaptive.shape != (9, 128, 128) or adaptive.dtype != bool
                or valid.shape != (9,) or valid.dtype != bool):
            raise ValueError('Unexpected fixture dimensions or uint16/boolean types')
        before = hashlib.sha256(b''.join(a.tobytes() for a in [boxes, core, roi, adaptive, valid])).hexdigest()
        regenerated_reference = choose_lut(boxes[:, 1], color='561', **config['reference_lut'])
        saved_luts = json.loads((source / 'luts.json').read_text())
        preserve = config.get('preserve_saved_reference_luts', True)
        reference = LUT(**saved_luts['561']) if preserve else regenerated_reference
        candidate = choose_lut(boxes[:, 1], roi, color='561', **config['candidate_lut'])
        lut488 = LUT(**saved_luts['488']) if preserve else choose_lut(boxes[:, 2], color='488', **config['reference_lut'])
        dest = review / nid
        dest.mkdir()
        copy_diagnostics(source, dest / 'source_diagnostics')
        lut_records = dict(reference=reference.metadata(), candidate=candidate.metadata(), identity488=lut488.metadata(),
                           regenerated_reference=regenerated_reference.metadata(), saved_reference_preserved=preserve,
                           bbox_policy=config['bbox_policy'], adopted_measurement_change=False)
        write_json(dest / 'luts.json', lut_records)
        params = json.loads((source / 'parameters.json').read_text())
        write_json(dest / 'resolved_parameters.json', build_resolved_parameters(repo, params))
        identity_links = links_if_present(dest / 'source_diagnostics', review, [
            ('segmentation_qc.csv', 'Per-visit 488 segmentation QC'), ('crop_geometry.json', '488-derived crop geometry'),
            ('soma_screen.json', 'Automated soma screen (not manual approval)')])
        identity_links += links_if_present(dest / 'source_diagnostics' / '00_roi', review, [
            ('01_consensus_vote_count.png', '488 consensus vote count image'),
            ('01_consensus_vote_count.json', 'Consensus vote count numeric diagnostics'),
            ('02_identity_core.png', 'Tight 488 consensus core'), ('03_phenotype_roi.png', 'Fixed phenotype ROI derived from 488'),
            ('diagnostics.json', 'ROI construction diagnostics')])
        identity_links += [relative_link(dest / 'resolved_parameters.json', review, 'Resolved algorithm parameters')]
        frames, identity_groups, phenotype_groups = [], [('Longitudinal ROI construction', identity_links)], []
        for i, day in enumerate(item['days']):
            base = apply_lut_for_display(boxes[i, 2], lut488)
            adaptive_view, core_view, roi_view = base.copy(), base.copy(), base.copy()
            adaptive_view[outline(adaptive[i])] = [255, 216, 100]
            core_view[outline(core)] = [0, 255, 255]
            roi_view[outline(roi)] = [255, 255, 255]
            identity_name, display_name, phenotype_name = [f'day_{day:02d}_{kind}.png' for kind in ['identity', 'display', 'phenotype']]
            make_qc_panel([base, adaptive_view, core_view, roi_view],
                          ['488 registered crop', 'Adaptive mask: amber', 'Consensus core: cyan', 'Phenotype ROI: white'],
                          cell=256).save(dest / identity_name)
            make_qc_panel([apply_lut_for_display(boxes[i, 1], reference), apply_lut_for_display(boxes[i, 1], candidate)],
                          ['Reference fixed LUT', 'ROI fixed LUT sensitivity'], cell=256).save(dest / display_name)
            shutil.copyfile(source / f'day_{day:02d}' / 'four_panel.png', dest / phenotype_name)
            clipping = {}
            for policy, lut in [('reference_bbox', reference), ('roi_fixed', candidate)]:
                stats = clipping_stats(boxes[i, 1], roi, lut)
                clipping[policy] = stats
                rows.append(dict(neuron_id=nid, day=day, display_policy=policy, low=lut.low, high=lut.high, **stats))
            source_day = dest / 'source_diagnostics' / f'day_{day:02d}'
            day_identity_links = links_if_present(source_day, review, [
                ('identity_488.png', 'Original 488 crop diagnostic'), ('identity_488.json', '488 intensity statistics and source hash'),
                ('adaptive_mask_488.png', 'Adaptive 488 mask image'), ('adaptive_mask_488.json', 'Adaptive mask numeric diagnostics'),
                ('provenance.json', 'Source paths, channel, day and code provenance')])
            phenotype_links = []
            for file in sorted(source_day.glob('*')):
                if file.suffix not in {'.png', '.json'} or file.name.startswith(('identity_', 'adaptive_mask_', 'provenance')):
                    continue
                phenotype_links.append(relative_link(file, review, file.stem.replace('_', ' ') + ' (' + file.suffix[1:] + ')'))
            identity_groups.append((f'Day {day}', day_identity_links))
            phenotype_groups.append((f'Day {day}', phenotype_links))
            frames.append(dict(day=day, identity=f'{nid}/{identity_name}', display=f'{nid}/{display_name}',
                               phenotype=f'{nid}/{phenotype_name}', adaptive_valid=bool(valid[i]), clipping=clipping,
                               identity_links=day_identity_links, phenotype_links=phenotype_links,
                               caption='128 × 128 unchanged geometry. Adaptive mask: amber. Consensus core: cyan. '
                               'Phenotype ROI: white. All identity geometry comes from 488.'))
        after = hashlib.sha256(b''.join(a.tobytes() for a in [boxes, core, roi, adaptive, valid])).hexdigest()
        if before != after:
            raise AssertionError('Rendering mutated quantitative evidence')
        identity_index, phenotype_index = [review / f'{nid}_{kind}_intermediates.html' for kind in ['identity', 'phenotype']]
        diagnostic_index(identity_index, neuron_id=nid, groups=identity_groups, identity=True)
        diagnostic_index(phenotype_index, neuron_id=nid, groups=phenotype_groups, identity=False)
        tracks.append(dict(neuron_id=nid, exclusion=config['known_exclusions'].get(nid, ''), frames=frames,
                           luts=lut_records, identity_links=identity_links, identity_index=identity_index.name,
                           phenotype_index=phenotype_index.name, quantitative_arrays_unchanged=True))
    with (review / 'lut_clipping.csv').open('w', newline='') as f:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    data = dict(tracks=tracks, config=config, raw561_definition='Registered 561 crop before local phenotype background correction',
                identity_source='488_only', phenotype_source='561_after_identity_and_roi')
    (review / 'review_data.js').write_text('window.TMEM_REVIEW_DATA = '
                                           + json.dumps(data, allow_nan=False).replace('<', '\\u003c') + ';\n')
    write_html(review / 'index.html')
    result = finalize_review_workspace(review, manifest, config['known_exclusions'])
    if result['verdict']['accepted_ids']:
        raise AssertionError('Blank manual review must not approve tracks')
    write_json(out / 'build_status.json', dict(execution_complete=True, tracks=len(manifest),
               neuron_days=sum(len(item['days']) for item in manifest), accepted_ids=[], manual_review='PENDING',
               source_metrics_unchanged=True, bbox_policy=config['bbox_policy'], ic_policy=config['ic_policy'],
               exact_rendered_evidence_bound=True, full_pipeline_complete=False))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--curated', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--evidence-root', type=Path)
    args = parser.parse_args()
    build(args.curated, args.config, args.out, args.evidence_root)


if __name__ == '__main__':
    main()
