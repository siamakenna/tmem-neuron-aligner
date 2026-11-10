"""Synthetic filesystem contracts; run only in the allocated verification job.

These tests exercise the actual input-record/run/resume/aggregate functions.
The processor writes a small text artifact; no ND2 parser or scientific import.
"""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import full_dataset as f


class CrossNodeIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.raw = self.root / 'originals'
        self.raw.mkdir()
        self.original = self.raw / 'Day8_WellE05.nd2'
        self.original.write_bytes(b'explicitly-synthetic-original-A')
        self.evidence = self.root / 'instrument_evidence.json'
        self.evidence.write_text('{"synthetic": "site evidence"}\n')
        self.flat = self.root / 'flat.dat'
        self.flat.write_bytes(b'synthetic-calibration-bytes')
        self.geometry = self.root / 'geometry.json'
        self.geometry.write_text('{"synthetic": "geometry"}\n')
        self.real_stat = f.stat_record
        header_stat = self.real_stat(self.original)
        # A distinct node-local mount number, while every shared-file field agrees.
        header_stat['device'] = 49
        self.task = {'id': 'E05__synthetic_site', 'well': 'E05', 'site': 'synthetic_site',
            'scope': 'field_series', 'observations': [{'path': str(self.original),
                'day': 8, 'header': {'stat': header_stat},
                'evidence': {'path': str(self.evidence), 'sha256': f.digest(self.evidence)},
                'calibration': {'flatfield': {'path': str(self.flat), 'sha256': f.digest(self.flat)}}}],
            'geometry_evidence': {'path': str(self.geometry), 'sha256': f.digest(self.geometry)}}
        self.source = {'fixture': 'synthetic filesystem identity only'}
        self.manifest = {'schema': f.SCHEMA, 'repo': str(self.root / 'repo'),
            'raw_root': str(self.raw), 'out_root': str(self.root / 'results'),
            'source': self.source, 'profile': {'days': [8], 'processing': {}},
            'tasks': [self.task], 'all_declared_positions_mapped': True}
        self.manifest['manifest_sha256'] = f.object_sha(self.manifest)
        self.processed = 0

    def node_stat(self, device):
        def stat(path):
            return dict(self.real_stat(path), device=device)
        return stat

    def processor(self, manifest, task, output):
        self.processed += 1
        (output / 'diagnostic.txt').write_text('synthetic filesystem test only\n')
        return {'days': [8], 'qc_failed_days': [8], 'fixture_only': True}

    def run_on(self, device, processor=None):
        with patch.object(f, 'source_binding', return_value=self.source), \
             patch.object(f, 'stat_record', side_effect=self.node_stat(device)):
            return f.run_task(self.manifest, self.task['id'], processor=processor or self.processor)

    def test_full_stat_record_retains_local_device_for_audit(self):
        record = f.stat_record(self.original)
        self.assertEqual(set(record), {'bytes', 'mtime_ns', 'device', 'inode'})
        self.assertEqual(record['device'], self.original.stat().st_dev)

    def test_portable_stat_excludes_only_device_without_mutating_audit_record(self):
        full = self.real_stat(self.original)
        before = deepcopy(full)
        portable = f.portable_stat_record(full)
        self.assertEqual(portable, {key: full[key] for key in ('bytes', 'mtime_ns', 'inode')})
        self.assertEqual(full, before)

    def test_node_mount_difference_is_accepted_with_identical_shared_identity(self):
        with patch.object(f, 'stat_record', side_effect=self.node_stat(48)):
            first = f.input_records(self.task)
        with patch.object(f, 'stat_record', side_effect=self.node_stat(49)):
            second = f.input_records(self.task)
        self.assertEqual(first, second)
        self.assertEqual(first[str(self.original)]['sha256'], f.digest(self.original))

    def test_every_input_kind_has_device_free_hash_bound_identity(self):
        with patch.object(f, 'stat_record', side_effect=self.node_stat(48)):
            records = f.input_records(self.task)
        self.assertEqual(set(records), {str(p) for p in (self.original, self.evidence, self.flat, self.geometry)})
        for path, record in records.items():
            self.assertEqual(set(record), {'bytes', 'mtime_ns', 'inode', 'sha256'})
            self.assertEqual(record['sha256'], f.digest(path))

    def test_size_mtime_or_inode_inventory_mismatch_still_fails_before_hash(self):
        for key in ('bytes', 'mtime_ns', 'inode'):
            task = deepcopy(self.task)
            task['observations'][0]['header']['stat'][key] += 1
            with self.subTest(key=key), patch.object(f, 'digest') as checksum, \
                 patch.object(f, 'stat_record', side_effect=self.node_stat(48)):
                with self.assertRaisesRegex(ValueError, 'after inventory'):
                    f.input_records(task)
                checksum.assert_not_called()

    def test_each_full_local_stat_change_during_hash_is_refused(self):
        before = dict(self.real_stat(self.original), device=48)
        for key in ('device', 'inode', 'bytes', 'mtime_ns'):
            after = dict(before); after[key] += 1
            with self.subTest(key=key), patch.object(f, 'stat_record', side_effect=[before, after]):
                with self.assertRaisesRegex(ValueError, 'during checksum read'):
                    f._hashed_input_record(self.original)

    def test_real_replacement_during_checksum_read_is_refused(self):
        real_digest = f.digest
        def changed(path):
            checksum = real_digest(path)
            replacement = self.root / 'replacement.bin'
            replacement.write_bytes(self.original.read_bytes())
            os.replace(replacement, self.original)
            return checksum
        with patch.object(f, 'digest', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'during checksum read'):
                f._hashed_input_record(self.original)

    def test_changed_acquisition_evidence_is_still_refused(self):
        self.evidence.write_text('{"synthetic": "tampered evidence"}\n')
        with patch.object(f, 'stat_record', side_effect=self.node_stat(48)):
            with self.assertRaisesRegex(ValueError, 'Acquisition site evidence changed'):
                f.input_records(self.task)

    def test_changed_calibration_is_still_refused(self):
        self.flat.write_bytes(b'changed-calibration')
        with patch.object(f, 'stat_record', side_effect=self.node_stat(48)):
            with self.assertRaisesRegex(ValueError, 'Calibration source bytes changed'):
                f.input_records(self.task)

    def test_changed_geometry_is_still_refused(self):
        self.geometry.write_text('{"synthetic": "changed geometry"}\n')
        with patch.object(f, 'stat_record', side_effect=self.node_stat(48)):
            with self.assertRaisesRegex(ValueError, 'Whole-well geometry evidence changed'):
                f.input_records(self.task)

    def test_actual_worker_resume_on_second_node_is_noop_and_preserves_outputs(self):
        first = self.run_on(48)
        def must_not_run(*args):
            raise AssertionError('A metadata-only mount difference must not rerun the processor')
        resumed = self.run_on(49, processor=must_not_run)
        self.assertTrue(resumed['resumed'])
        self.assertEqual(first['binding'], resumed['binding'])
        self.assertEqual(first['outputs'], resumed['outputs'])
        self.assertEqual(self.processed, 1)
        self.assertTrue(all('device' not in record for record in first['inputs'].values()))

    def test_actual_aggregate_hashes_originals_successfully_on_second_node(self):
        self.run_on(48)
        with patch.object(f, 'source_binding', return_value=self.source), \
             patch.object(f, 'stat_record', side_effect=self.node_stat(49)):
            summary = f.aggregate(self.manifest, hash_inputs=True)
        self.assertTrue(summary['source_pixels_rehashed'])
        self.assertTrue(summary['execution_complete'])
        self.assertEqual(summary['completed'], 1)
        self.assertEqual(summary['tasks'][0]['qc_failed_days'], [8])

    def test_content_change_with_same_size_inode_mtime_still_refuses_resume(self):
        first = self.run_on(48)
        before = self.original.stat()
        data = self.original.read_bytes()
        self.original.write_bytes(data[:-1] + b'B')
        os.utime(self.original, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'conflicts with changed inputs'):
            self.run_on(49)
        retained = f.load(Path(self.manifest['out_root']) / self.task['id'] / 'COMPLETED.json')
        self.assertEqual(retained, first)
        self.assertEqual(self.processed, 1)

    def test_source_change_during_processing_fails_and_retains_attempt(self):
        def mutate(manifest, task, output):
            self.original.write_bytes(b'changed-during-processing')
            return self.processor(manifest, task, output)
        with self.assertRaisesRegex(ValueError, 'after inventory|changed during execution'):
            self.run_on(48, processor=mutate)
        root = Path(self.manifest['out_root']) / self.task['id']
        self.assertFalse((root / 'COMPLETED.json').exists())
        self.assertEqual(len(list((root / 'attempts').glob('*/FAILED.json'))), 1)
        self.assertFalse((root / 'ACTIVE.lock').exists())


if __name__ == '__main__':
    unittest.main()
