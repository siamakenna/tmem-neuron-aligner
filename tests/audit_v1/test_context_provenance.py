import subprocess
import unittest
from unittest import mock
from tmem_align.audit_v1 import commands


class PortableContextTests(unittest.TestCase):
    def test_no_git_binary_retains_exact_source_hashes(self):
        with mock.patch.object(commands.subprocess, 'run', side_effect=FileNotFoundError('git')):
            result = commands.context('portable', 'SYNTHETIC')
        self.assertFalse(result['git_checkout'])
        self.assertEqual(result['checkout_commit'], 'unavailable-source-snapshot')
        self.assertIn('src/tmem_align/audit_v1/commands.py', result['audit_code_sha256'])

    def test_unrelated_ancestor_checkout_cannot_label_the_snapshot(self):
        ancestor = subprocess.CompletedProcess([], 0, stdout='/unrelated-project\n', stderr='')
        with mock.patch.object(commands.subprocess, 'run', return_value=ancestor) as run:
            result = commands.context('portable', 'SYNTHETIC')
        self.assertFalse(result['git_checkout'])
        self.assertEqual(result['working_tree'], 'unavailable-source-snapshot')
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
