"""Review decisions bind the portable files that a scientist actually sees."""
import copy
import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tmem_align.audit_v1.review_gate import (
    CRITERIA, DAYS, EVIDENCE_FILES, RENDERED_SCHEMA_VERSION, evidence_manifest,
    evaluate_review, finalize_review_workspace, make_review_template,
    rendered_manifest, verify_review_workspace,
)


class RenderBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.curated=self.root/'fixtures';self.curated.mkdir()
        self.nid='J05_N015';folder=self.curated/self.nid;folder.mkdir()
        for name in EVIDENCE_FILES:(folder/name).write_bytes(b'unchanged quantitative evidence')
        for name in ['metrics.csv','fixture_tracks.csv']:
            with (folder/name).open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['neuron_id','well','day']);w.writeheader()
                w.writerows(dict(neuron_id=self.nid,well='J05',day=day) for day in DAYS)
        self.source=evidence_manifest(self.curated,[self.nid])
        self.review=self.root/'workspace'/'review';self.review.mkdir(parents=True)
        for name in ['index.html','ui.js','review_data.js','config.json','lut_clipping.csv']:
            (self.review/name).write_text('fixed display evidence '+name)
        sub=self.review/self.nid;sub.mkdir();(sub/'luts.json').write_text('{"low":1,"high":2}')
        diagnostics=sub/'source_diagnostics';diagnostics.mkdir()
        (diagnostics/'adaptive_mask.png').write_bytes(b'adaptive 488 mask')
        for day in DAYS:
            for kind in ['identity','display','phenotype']:
                (sub/f'day_{day:02d}_{kind}.png').write_bytes(f'{day}:{kind}'.encode())
        self.finalized=finalize_review_workspace(self.review,self.source,{})
        self.sha=self.finalized['render_manifest']['workspace_sha256']

    def accepted(self):
        doc=copy.deepcopy(self.finalized['template']);doc['reviewer']='Synthetic test reviewer'
        doc['reviewed_at']='2026-10-20T18:00:00+00:00'
        for track in doc['tracks']:
            track['track_decision']='accept'
            for visit in track['visits']:visit.update({k:'pass' for k in CRITERIA})
        return doc

    def test_bound_template_is_v2_and_stays_unreviewed(self):
        doc=self.finalized['template']
        self.assertEqual(doc['schema_version'],RENDERED_SCHEMA_VERSION)
        self.assertEqual(doc['workspace_sha256'],self.sha)
        self.assertEqual(self.finalized['verdict']['accepted_ids'],[])
        self.assertEqual(set(doc['tracks'][0]['visits'][0]),
                         {'day',*CRITERIA,'notes','failure_category'})
        self.assertEqual(verify_review_workspace(self.review,self.source,{}),self.finalized['render_manifest'])

    def test_complete_review_requires_exact_render_fingerprint(self):
        doc=self.accepted()
        self.assertEqual(evaluate_review(doc,self.source,{},workspace_sha256=self.sha)['accepted_ids'],[self.nid])
        for value in [None,'0'*64]:
            with self.subTest(value=value):
                changed=copy.deepcopy(doc);changed['workspace_sha256']=value
                self.assertEqual(evaluate_review(changed,self.source,{},workspace_sha256=self.sha)['accepted_ids'],[])

    def test_changed_shown_assets_or_configuration_fail_verification(self):
        paths=['index.html','ui.js','review_data.js','config.json','lut_clipping.csv',
               f'{self.nid}/luts.json',f'{self.nid}/day_08_identity.png',
               f'{self.nid}/day_12_display.png',f'{self.nid}/source_diagnostics/adaptive_mask.png']
        for name in paths:
            with self.subTest(asset=name):
                p=self.review/name;before=p.read_bytes();p.write_bytes(before+b' changed')
                with self.assertRaisesRegex(ValueError,'changed or stale'):
                    verify_review_workspace(self.review,self.source,{})
                p.write_bytes(before)
                self.assertEqual(evidence_manifest(self.curated,[self.nid]),self.source)

    def test_binding_script_and_pending_records_are_independently_checked(self):
        for name in ['review_binding.js','manual_review_template.json','pending_review_verdicts.json']:
            with self.subTest(asset=name):
                p=self.review/name;before=p.read_bytes();p.write_bytes(before+b'\n')
                with self.assertRaisesRegex(ValueError,'changed or stale'):
                    verify_review_workspace(self.review,self.source,{})
                p.write_bytes(before)

    def test_missing_display_or_symbolic_link_cannot_be_accepted(self):
        p=self.review/self.nid/'day_20_identity.png';before=p.read_bytes();p.unlink()
        with self.assertRaises(ValueError):verify_review_workspace(self.review,self.source,{})
        outside=self.root/'outside.png';outside.write_bytes(before);p.symlink_to(outside)
        with self.assertRaises(ValueError):verify_review_workspace(self.review,self.source,{})

    def test_changed_source_invalidates_render_binding(self):
        p=self.curated/self.nid/'small_fixture.npz';p.write_bytes(b'different source')
        fresh=evidence_manifest(self.curated,[self.nid])
        with self.assertRaisesRegex(ValueError,'changed or stale'):
            verify_review_workspace(self.review,fresh,{})

    def test_unchanged_package_remains_valid_after_move(self):
        destination=self.root/'moved handoff'
        shutil.copytree(self.root/'workspace',destination/'workspace')
        shutil.copytree(self.curated,destination/'fixtures')
        fresh=evidence_manifest(destination/'fixtures',[self.nid])
        actual=verify_review_workspace(destination/'workspace',fresh,{})
        self.assertEqual(actual,self.finalized['render_manifest'])

    def test_finder_metadata_does_not_invalidate_unchanged_review_evidence(self):
        (self.review/'.DS_Store').write_bytes(b'Finder folder view metadata')
        (self.review/self.nid/'.DS_Store').write_bytes(b'Another folder view')
        self.assertEqual(verify_review_workspace(self.review,self.source,{}),
                         self.finalized['render_manifest'])

    def test_rebuilding_changed_display_invalidates_an_old_review(self):
        old=self.accepted()
        (self.review/self.nid/'day_29_display.png').write_bytes(b'new candidate LUT display')
        for name in ['render_manifest.json','review_binding.js','manual_review_template.json','pending_review_verdicts.json']:
            (self.review/name).unlink()
        rebuilt=finalize_review_workspace(self.review,self.source,{})
        new_sha=rebuilt['render_manifest']['workspace_sha256']
        self.assertNotEqual(self.sha,new_sha)
        self.assertEqual(evaluate_review(old,self.source,{},workspace_sha256=new_sha)['accepted_ids'],[])

    def test_old_schema_and_invalid_visit_annotations_are_rejected(self):
        old=make_review_template(self.source)
        with self.assertRaisesRegex(ValueError,'schema'):
            evaluate_review(old,self.source,{},workspace_sha256=self.sha)
        doc=self.accepted();doc['tracks'][0]['visits'][0]['failure_category']='unclassified_value'
        with self.assertRaisesRegex(ValueError,'category'):
            evaluate_review(doc,self.source,{},workspace_sha256=self.sha)

    def test_finalization_does_not_overwrite_existing_reviews(self):
        with self.assertRaises(FileExistsError):finalize_review_workspace(self.review,self.source,{})


if __name__=='__main__':unittest.main()
