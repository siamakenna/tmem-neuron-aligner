import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.export_reviewed_metrics import export,portable_git_commit
from tmem_align.audit_v1.review_gate import DAYS,evidence_manifest,finalize_review_workspace,make_review_template


def bind_workspace(root,curated,config):
    """Small display-asset fixture; image decoding is the builder's own gate."""
    root.mkdir()
    config_data=json.loads(config.read_text())
    (root/'config.json').write_text(config.read_text())
    for name in ['index.html','ui.js','review_data.js','lut_clipping.csv']:
        (root/name).write_text('deterministic '+name)
    for nid in config_data['neuron_ids']:
        folder=root/nid;folder.mkdir();(folder/'luts.json').write_text('{"low": 0, "high": 100}')
        for day in DAYS:
            for kind in ['identity','display','phenotype']:
                (folder/f'day_{day:02d}_{kind}.png').write_bytes(f'{nid}:{day}:{kind}'.encode())
    source=evidence_manifest(curated,config_data['neuron_ids'])
    return finalize_review_workspace(root,source,config_data['known_exclusions'])['template']


class ExportIntegration(unittest.TestCase):
    def setup_files(self,root,valid=True):
        nid='E05_N001';folder=root/'curated'/nid;folder.mkdir(parents=True)
        for name in ['small_fixture.npz','parameters.json','luts.json']:(folder/name).write_bytes(b'fixture')
        metrics=[];tracks=[]
        for day in DAYS:
            metrics.append(dict(neuron_id=nid,well='E05',day=day,adaptive_valid=valid,single_soma_pass=True,
                phenotype_roi_area=20,total_mcherry_intensity=100,punctate_mcherry_integrated_intensity=30,
                diffuse_mcherry_integrated_intensity=70,puncta_count=1,review='MANUAL_REVIEW_REQUIRED'))
            tracks.append(dict(neuron_id=nid,well='E05',day=day,tracking_valid=True,
                global_reg_qc_pass=True,global_reg_well_registration_qc_pass=True))
        for name,rows in [('metrics.csv',metrics),('fixture_tracks.csv',tracks)]:
            with (folder/name).open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        config=root/'config.json';config.write_text(json.dumps(dict(neuron_ids=[nid],known_exclusions={},
            biological_pairs=[['E05','F05'],['I05','J05'],['M05','N05']],ic_policy='off')))
        self.workspace=root/'workspace'
        review=bind_workspace(self.workspace,root/'curated',config)
        return root/'curated',config,review

    def save_review(self,root,review,accepted=False):
        if accepted:
            review['reviewer']='Unit-test reviewer';review['reviewed_at']='2026-10-20T17:00:00+00:00'
            for track in review['tracks']:
                track['track_decision']='accept'
                for visit in track['visits']:
                    for field in ['identity_488','roi_purity_488','phenotype_qc_561']:visit[field]='pass'
        path=root/'reviews.json';path.write_text(json.dumps(review));return path

    def test_pending_review_never_writes_accepted_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,review=self.setup_files(root)
            status=export(curated,self.save_review(root,review),config,root/'out',workspace=self.workspace)
            self.assertEqual(status,2);self.assertFalse((root/'out/accepted_neuron_metrics.csv').exists())

    def test_reviewed_valid_track_releases_exact_nine_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,review=self.setup_files(root)
            source=(curated/'E05_N001/metrics.csv').read_bytes()
            status=export(curated,self.save_review(root,review,True),config,root/'out',workspace=self.workspace)
            self.assertEqual(status,0)
            with (root/'out/accepted_neuron_metrics.csv').open() as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),9);self.assertEqual({r['total_mcherry_intensity'] for r in rows},{'100'})
            self.assertEqual(source,(curated/'E05_N001/metrics.csv').read_bytes())
            self.assertFalse(json.loads((root/'out/analysis_scope.json').read_text())['inference_ready'])
            self.assertEqual(json.loads((root/'out/analysis_scope.json').read_text())['review_workspace_sha256'],
                             review['workspace_sha256'])

    def test_manual_pass_cannot_override_failed_automated_qc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,review=self.setup_files(root,valid=False)
            status=export(curated,self.save_review(root,review,True),config,root/'out',workspace=self.workspace)
            self.assertEqual(status,2);self.assertFalse((root/'out/accepted_neuron_metrics.csv').exists())

    def test_missing_finite_quantities_blocks_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,review=self.setup_files(root)
            file=curated/'E05_N001/metrics.csv'
            with file.open() as f:rows=list(csv.DictReader(f))
            rows[0]['total_mcherry_intensity']='nan'
            with file.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            self.workspace=root/'workspace-nan';review=bind_workspace(self.workspace,curated,config)
            status=export(curated,self.save_review(root,review,True),config,root/'out',workspace=self.workspace)
            self.assertEqual(status,2);self.assertFalse((root/'out/accepted_neuron_metrics.csv').exists())

    def test_changed_visual_evidence_invalidates_old_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,_=self.setup_files(root)
            folder=curated/'E05_N001'
            for day in DAYS:
                p=folder/f'day_{day:02d}';p.mkdir();(p/'four_panel.png').write_bytes(b'original visual evidence')
            self.workspace=root/'workspace-panels';review=bind_workspace(self.workspace,curated,config)
            saved=self.save_review(root,review,True)
            (folder/'day_20/four_panel.png').write_bytes(b'changed visual evidence')
            with self.assertRaisesRegex(ValueError,'Rendered review evidence'):
                export(curated,saved,config,root/'out',workspace=self.workspace)
            self.assertFalse((root/'out/accepted_neuron_metrics.csv').exists())

    def test_legacy_review_cannot_release_v6_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,_=self.setup_files(root)
            legacy=make_review_template(evidence_manifest(curated,['E05_N001']))
            with self.assertRaisesRegex(ValueError,'schema'):
                export(curated,self.save_review(root,legacy,True),config,root/'out',workspace=self.workspace)
            self.assertFalse((root/'out/accepted_neuron_metrics.csv').exists())

    def test_displayed_identity_change_blocks_export_with_unchanged_quantities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,review=self.setup_files(root)
            saved=self.save_review(root,review,True)
            (self.workspace/'E05_N001/day_08_identity.png').write_bytes(b'different identity image')
            with self.assertRaisesRegex(ValueError,'Rendered review evidence'):
                export(curated,saved,config,root/'out',workspace=self.workspace)
            self.assertFalse((root/'out/accepted_neuron_metrics.csv').exists())

    def test_missing_workspace_cannot_release_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,review=self.setup_files(root)
            with self.assertRaisesRegex(ValueError,'requires --workspace'):
                export(curated,self.save_review(root,review,True),config,root/'out')

    def test_config_different_from_reviewed_config_blocks_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);curated,config,review=self.setup_files(root)
            changed=json.loads(config.read_text());changed['ic_policy']='different policy'
            config.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'configuration differs'):
                export(curated,self.save_review(root,review,True),config,root/'out',workspace=self.workspace)
            self.assertFalse((root/'out/accepted_neuron_metrics.csv').exists())

    def test_portable_source_does_not_require_or_inherit_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('scripts.export_reviewed_metrics.subprocess.run',side_effect=FileNotFoundError) as run:
                self.assertEqual(portable_git_commit(root),'source_snapshot')
                run.assert_not_called()
            (root/'.git').mkdir()
            with patch('scripts.export_reviewed_metrics.subprocess.run',side_effect=FileNotFoundError):
                self.assertEqual(portable_git_commit(root),'source_snapshot')
