"""Inspect actual generated review evidence and exercise its offline controls."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

from tmem_align.audit_v1.review_gate import DAYS, evidence_manifest, verify_review_workspace


REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('build_review_workspace', REPO / 'scripts/build_review_workspace.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def fixture(root, neuron_id):
    folder = root / neuron_id
    folder.mkdir()
    box = np.zeros((9, 3, 128, 128), dtype=np.uint16)
    yy, xx = np.indices((128, 128))
    box[:, 2] = (xx + yy).astype(np.uint16)
    box[:, 1] = (2 * xx + yy).astype(np.uint16)
    core = (xx - 64) ** 2 + (yy - 64) ** 2 < 36
    roi = (xx - 64) ** 2 + (yy - 64) ** 2 < 64
    adaptive = np.repeat(core[None], 9, axis=0)
    # One adaptive mask differs from the fixed core, so the panel must expose it.
    adaptive[1, 64, 45:65] = True
    np.savez_compressed(folder / 'small_fixture.npz', boxes_tcyx=box, identity_core=core,
                        phenotype_roi=roi, adaptive_masks=adaptive, adaptive_valid=np.ones(9, dtype=bool))
    for name in ['metrics.csv', 'fixture_tracks.csv']:
        with (folder / name).open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['neuron_id', 'well', 'day'])
            writer.writeheader()
            writer.writerows(dict(neuron_id=neuron_id, well=neuron_id[:3], day=day) for day in DAYS)
    params = dict(bbox_size=128, identity_consensus_fraction=0.6, phenotype_dilation=2,
                  segmentation_min_area=180, min_core_area=80, max_core_area=2500,
                  background_exclusion=8, puncta_min_size=6)
    (folder / 'parameters.json').write_text(json.dumps(params))
    luts = {channel: dict(low=0, high=400, color=channel, source='deterministic test',
                         scope='fixed-longitudinal-per-neuron') for channel in ['488', '561']}
    (folder / 'luts.json').write_text(json.dumps(luts))
    (folder / 'segmentation_qc.csv').write_text('day,adaptive_valid\n8,True\n')
    roi_dir = folder / '00_roi'
    roi_dir.mkdir()
    for name in ['01_consensus_vote_count', '02_identity_core', '03_phenotype_roi']:
        Image.new('RGB', (128, 128), 'black').save(roi_dir / (name + '.png'))
        (roi_dir / (name + '.json')).write_text('{}\n')
    for day in DAYS:
        target = folder / f'day_{day:02d}'
        target.mkdir()
        for name in ['four_panel', 'adaptive_mask_488', 'identity_488', '00_raw_561', '05_puncta_candidates']:
            Image.new('RGB', (128, 128), 'black').save(target / (name + '.png'))
            (target / (name + '.json')).write_text('{}\n')
    return folder


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.curated = cls.root / 'fixtures'
        cls.curated.mkdir()
        for nid in ['J05_N015', 'N05_N011', 'F05_N025']:
            fixture(cls.curated, nid)
        cls.config_path = cls.root / 'config.json'
        config = json.loads((REPO / 'configs/tmem_review_v5.json').read_text())
        cls.config_path.write_text(json.dumps(config))
        cls.original_hashes = {str(p.relative_to(cls.curated)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in cls.curated.rglob('*') if p.is_file()}
        cls.workspace = cls.root / 'workspace'
        builder.build(cls.curated, cls.config_path, cls.workspace)
        cls.review = cls.workspace / 'review'
        text = (cls.review / 'review_data.js').read_text()
        cls.data = json.loads(text.removeprefix('window.TMEM_REVIEW_DATA = ').rstrip('\n;'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_source_arrays_and_artifacts_remain_byte_identical(self):
        current = {str(p.relative_to(self.curated)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in self.curated.rglob('*') if p.is_file()}
        self.assertEqual(current, self.original_hashes)
        status = json.loads((self.workspace / 'build_status.json').read_text())
        self.assertEqual(status['accepted_ids'], [])
        self.assertTrue(status['exact_rendered_evidence_bound'])

    def test_adaptive_core_roi_and_lut_diagnostics_are_inspectable(self):
        tracks = self.data['tracks']
        self.assertEqual(len(tracks), 3)
        for track in tracks:
            self.assertEqual(len(track['frames']), 9)
            self.assertTrue((self.review / track['identity_index']).is_file())
            identity_index = (self.review / track['identity_index']).read_text()
            self.assertNotIn('00_raw_561.png', identity_index)
            self.assertIn('consensus_vote_count.png', identity_index)
            for frame in track['frames']:
                for kind in ['identity', 'display', 'phenotype']:
                    self.assertTrue((self.review / frame[kind]).is_file())
                for link in frame['identity_links'] + frame['phenotype_links'] + track['identity_links']:
                    self.assertTrue((self.review / link['href']).is_file(), link)
                self.assertEqual(frame['clipping']['reference_bbox']['quantitative_sum'],
                                 frame['clipping']['roi_fixed']['quantitative_sum'])
        image = np.asarray(Image.open(self.review / tracks[0]['frames'][1]['identity']))
        self.assertEqual(image.shape, (304, 1024, 3))
        for color in [[255, 216, 100], [0, 255, 255], [255, 255, 255]]:
            self.assertTrue(np.any(np.all(image[48:] == color, axis=-1)))
        params = json.loads((self.review / 'J05_N015/resolved_parameters.json').read_text())
        self.assertTrue(params)

    def test_render_manifest_binds_ui_data_and_intermediates(self):
        source = evidence_manifest(self.curated, self.data['config']['neuron_ids'])
        actual = verify_review_workspace(self.review, source, self.data['config']['known_exclusions'])
        self.assertTrue(actual['workspace_sha256'])
        names = actual['files']
        for name in ['ui.js', 'index.html', 'review_data.js', 'config.json',
                     'J05_N015/resolved_parameters.json',
                     'J05_N015/source_diagnostics/day_12/adaptive_mask_488.png']:
            self.assertIn(name, names)

    def test_optional_external_evidence_is_copied_and_indexed(self):
        evidence = self.root / 'evidence_input'
        evidence.mkdir()
        (evidence / 'index.html').write_text('<h1>Historical real-data evidence</h1>')
        destination = self.root / 'with_evidence'
        builder.build(self.curated, self.config_path, destination, evidence)
        config = json.loads((destination / 'review/config.json').read_text())
        self.assertEqual(config['evidence_index'], '../evidence/index.html')
        self.assertEqual((destination / 'evidence/index.html').read_bytes(), (evidence / 'index.html').read_bytes())

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for the offline UI workflow check')
    def test_offline_controls_save_resume_and_stale_rejection(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('check_review_ui.js')), str(self.review)],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS:', result.stdout)


if __name__ == '__main__':
    unittest.main()
