"""Exercise portable packaging without depending on the microscopy runtime."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('handoff_packager', ROOT / 'scripts/make_claire_handoff.py')
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)


class HandoffPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'source snapshot'
        for folder in ('src/tmem_align', 'scripts', 'tests', 'configs', 'docs/audit_v1'):
            (self.repo / folder).mkdir(parents=True)
        (self.repo / 'src/tmem_align/__init__.py').write_text('')
        (self.repo / 'scripts/review_ui.js').write_text('const unchanged=true;\n')
        (self.repo / 'README.md').write_text('Read docs/audit_v1/IMPLEMENTATION.md\n')
        (self.repo / 'pyproject.toml').write_text('[project]\nname="test-snapshot"\nversion="0.0"\n')
        (self.repo / 'docs/audit_v1/IMPLEMENTATION.md').write_text('Current handoff commands\n')
        (self.repo / 'docs/audit_v1/claire_stress_cases.csv').write_text(
            'case,expected_result,observed_result,reviewer,actual_classification,failure_classification,execution_status,execution_role,notes\n'
            'blank_488,reject,old result,old reviewer,new_bug,new_bug,PASS,developer,old note\n')
        self.config = {'neuron_ids': ['J05_N015'], 'known_exclusions': {}}
        (self.repo / 'configs/tmem_review_v6.json').write_text(json.dumps(self.config))
        self.curated = self.root / 'curated'
        (self.curated / 'J05_N015').mkdir(parents=True)
        (self.curated / 'J05_N015/metrics.csv').write_text('immutable fixture values\n')
        self.workspace = self.root / 'workspace'
        (self.workspace / 'review').mkdir(parents=True)
        (self.workspace / 'review/index.html').write_text('<img src="identity.png">')
        (self.workspace / 'review/identity.png').write_bytes(b'original-pixels')
        (self.workspace / 'evidence').mkdir()
        (self.workspace / 'evidence/index.html').write_text('Real evidence, labeled historical')
        (self.workspace / 'evidence/SHA256SUMS').write_text('historical checksum record')
        self.verification = self.root / 'verification'
        self.verification.mkdir()
        (self.verification / 'all_tests.log').write_text('Current run passed\n')
        (self.verification / 'all_tests.xml').write_text('<testsuite failures="0"/>')
        (self.verification / 'source_install.json').write_text('{"v6_source":true}')
        self.environment = {'python_version': '3.11 test', 'platform': 'test-platform',
                            'top_level_versions': {n: '1.0' for n in PACKAGER.PINNED_DISTRIBUTIONS},
                            'pip_freeze': 'test-package==1.0\n'}
        self.out = self.root / 'handoff.zip'
        verified_source = {'source/' + str(p.relative_to(self.repo)): PACKAGER.digest(p)
                           for p in self.repo.rglob('*') if p.is_file()}
        verified_evidence = {}
        for folder, source in [('fixtures', self.curated), ('review', self.workspace / 'review'),
                               ('evidence', self.workspace / 'evidence')]:
            verified_evidence.update({folder + '/' + str(p.relative_to(source)): PACKAGER.digest(p)
                                      for p in source.rglob('*') if p.is_file()})
        (self.verification / 'source_snapshot.json').write_text(json.dumps(
            {'source_sha256': verified_source, 'review_evidence_sha256': verified_evidence,
             'manifest_sha256': 'verified-candidate-manifest'}))

    def build(self, **kwargs):
        return PACKAGER.build_handoff(self.repo, self.curated, self.workspace, self.out,
                                      environment=self.environment, **kwargs)

    def test_fresh_snapshot_has_complete_manifest_and_preserves_source_and_review(self):
        result = self.build(verification_root=self.verification)
        self.assertFalse(result['source']['git_checkout'])
        self.assertTrue(result['current_source_install_included'])
        self.assertEqual(result['verification_scope']['status'], 'same_tested_inputs')
        with zipfile.ZipFile(self.out) as archive:
            self.assertIsNone(archive.testzip())
            manifest = archive.read('SHA256SUMS').decode().splitlines()
            named = set()
            for line in manifest:
                expected, name = line.split('  ', 1)
                named.add(name)
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
            self.assertEqual(named, set(archive.namelist()) - {'SHA256SUMS'})
            self.assertEqual(archive.read('review/identity.png'), b'original-pixels')
            self.assertEqual(archive.read('fixtures/J05_N015/metrics.csv'), b'immutable fixture values\n')
            self.assertIn('source/scripts/review_ui.js', named)
            self.assertIn('evidence/SHA256SUMS', named)
            self.assertIn('provenance/current_source_install.json', named)
            snapshot = json.loads(archive.read('provenance/source_snapshot.json'))
            for name, expected in snapshot['included_source_sha256'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)

    def test_human_outcomes_cleared_without_changing_case_expectation(self):
        self.build()
        with zipfile.ZipFile(self.out) as archive:
            rows = list(csv.DictReader(io.StringIO(archive.read('stress_results.csv').decode())))
        self.assertEqual(rows[0]['expected_result'], 'reject')
        for field in ('observed_result', 'reviewer', 'actual_classification',
                      'failure_classification', 'execution_status', 'execution_role', 'notes'):
            self.assertEqual(rows[0][field], '')

    def test_current_reports_cannot_be_advertised_when_incomplete(self):
        (self.verification / 'all_tests.xml').unlink()
        with self.assertRaisesRegex(ValueError, 'all_tests.xml'):
            self.build(verification_root=self.verification)
        self.assertFalse(self.out.exists())

    def test_existing_archive_never_overwritten(self):
        self.out.write_bytes(b'old handoff')
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.out.read_bytes(), b'old handoff')

    def test_fixture_symlink_rejected(self):
        (self.curated / 'J05_N015/linked.json').symlink_to(self.repo / 'configs/tmem_review_v6.json')
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            self.build()
        self.assertFalse(self.out.exists())

    def test_missing_evidence_is_disclosed_and_not_linked_as_available(self):
        (self.workspace / 'evidence/index.html').unlink()
        (self.workspace / 'evidence/SHA256SUMS').unlink()
        (self.workspace / 'evidence').rmdir()
        result = self.build()
        self.assertFalse(result['real_evidence_included'])
        with zipfile.ZipFile(self.out) as archive:
            html = archive.read('index.html').decode()
        self.assertNotIn('href="evidence/index.html"', html)
        self.assertIn('unavailable', html)

    def test_evidence_index_links_existing_stage_outputs_and_omits_missing_ones(self):
        stage = self.verification/'production_stress'
        stage.mkdir()
        (stage/'index.html').write_text('Measured production response')
        self.build(verification_root=self.verification)
        with zipfile.ZipFile(self.out) as archive:
            page = archive.read('index.html').decode()
        self.assertIn('href="verification/production_stress/index.html"', page)
        self.assertNotIn('href="verification/synthetic/02_alignment/slides.html"', page)

    def test_source_changed_after_verification_is_rejected(self):
        (self.repo / 'scripts/review_ui.js').write_text('changed after test')
        with self.assertRaisesRegex(ValueError, 'source differs'):
            self.build(verification_root=self.verification)
        self.assertFalse(self.out.exists())

    def test_display_changed_after_verification_is_rejected(self):
        (self.workspace / 'review/identity.png').write_bytes(b'different shown image')
        with self.assertRaisesRegex(ValueError, 'fixtures/review/evidence differ'):
            self.build(verification_root=self.verification)
        self.assertFalse(self.out.exists())

    def test_current_logs_without_tested_input_record_are_rejected(self):
        (self.verification / 'source_snapshot.json').unlink()
        with self.assertRaisesRegex(ValueError, 'source_snapshot.json'):
            self.build(verification_root=self.verification)
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
