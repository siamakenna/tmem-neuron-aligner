"""File-integrity and result-count tests; these do not fake microscopy tests."""
import importlib.util
import io
from pathlib import Path
import stat
import unittest
from unittest.mock import patch
import zipfile

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "summarize_stage_evidence.py"
_SPEC = importlib.util.spec_from_file_location("stage_evidence", _PATH)
evidence = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(evidence)


def archive_bytes(files=None, checksum_override=None, extra=None):
    files = {"record.json": b'{"value": 1}'} if files is None else files
    sums = "".join(evidence.digest(value) + "  " + name + "\n"
                   for name, value in files.items()).encode()
    if checksum_override is not None:
        sums = checksum_override
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, value in files.items():
            archive.writestr("packet/" + name, value)
        archive.writestr("packet/SHA256SUMS", sums)
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    return buf.getvalue()


class ArchiveIntegrityTests(unittest.TestCase):
    def test_good_inventory(self):
        z, prefix, hashes = evidence.validated_archive(archive_bytes())
        try:
            self.assertEqual(prefix, "packet/")
            self.assertEqual(len(hashes), 1)
        finally:
            z.close()

    def test_corrupted_checksum_rejected(self):
        data = archive_bytes(checksum_override=b"0" * 64 + b"  record.json\n")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            evidence.validated_archive(data)

    def test_unlisted_member_rejected(self):
        data = archive_bytes(extra={"packet/extra.json": b"{}"})
        with self.assertRaisesRegex(ValueError, "unlisted"):
            evidence.validated_archive(data)

    def test_missing_member_rejected(self):
        data = archive_bytes(checksum_override=b"0" * 64 + b"  absent.json\n")
        with self.assertRaisesRegex(ValueError, "missing"):
            evidence.validated_archive(data)

    def test_traversal_rejected_even_when_listed(self):
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            evidence.validated_archive(archive_bytes({"../escape": b"x"}))

    def test_absolute_and_windows_paths_rejected(self):
        for name in ["/tmp/x", "../x", "a/../x", "a\\b", "a//b", "./a"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                evidence.safe_name(name)

    def test_duplicate_member_rejected(self):
        data = archive_bytes(extra={"packet/record.json": b"x"})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            evidence.validated_archive(data)

    def test_symlink_rejected(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            link = zipfile.ZipInfo("packet/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(link, "target")
            z.writestr("packet/SHA256SUMS", "")
        with self.assertRaisesRegex(ValueError, "links"):
            evidence.validated_archive(b.getvalue())

    def test_expansion_limit_precedes_member_read(self):
        with patch.object(evidence, "MAX_EXPANDED", 1):
            with self.assertRaisesRegex(ValueError, "size limit"):
                evidence.validated_archive(archive_bytes())

    def test_checksum_self_reference_rejected(self):
        data = archive_bytes(checksum_override=b"0" * 64 + b"  SHA256SUMS\n")
        with self.assertRaisesRegex(ValueError, "self-referential"):
            evidence.validated_archive(data)


class TestCountTests(unittest.TestCase):
    def xml(self, tests=86, failures=0, skipped=0):
        return (f'<testsuites><testsuite tests="{tests}" failures="{failures}" '
                f'errors="0" skipped="{skipped}" /></testsuites>').encode()

    def test_counts_distinguish_subtests(self):
        result = evidence.phase_result(self.xml(), b"55 passed, 31 subtests passed in 0.89s\n")
        self.assertEqual(result["tests_passed"], 55)
        self.assertEqual(result["subtests_passed"], 31)
        self.assertEqual(result["counted_executions"], 86)

    def test_disagreeing_log_rejected(self):
        with self.assertRaisesRegex(ValueError, "disagrees"):
            evidence.phase_result(self.xml(), b"86 passed, 31 subtests passed in 0.89s\n")

    def test_missing_or_ambiguous_terminal_summary_rejected(self):
        for log in [b"working", b"55 passed, 31 subtests passed in 1.0s\n" * 2]:
            with self.subTest(log=log), self.assertRaisesRegex(ValueError, "summary"):
                evidence.phase_result(self.xml(), log)

    def test_failed_skipped_empty_phases_rejected(self):
        for xml in [self.xml(failures=1), self.xml(skipped=1), self.xml(tests=0)]:
            with self.subTest(xml=xml), self.assertRaisesRegex(ValueError, "empty, failed, or skipped"):
                evidence.phase_result(xml, b"55 passed, 31 subtests passed in 0.89s\n")

    def test_doctype_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            evidence.phase_result(b'<!DOCTYPE foo><testsuites />', b"")


if __name__ == "__main__":
    unittest.main()
