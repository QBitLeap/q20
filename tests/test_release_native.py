"""Release the exact accepted native image; archive identity fails before Docker."""
from hashlib import sha256
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('q20_release_native',ROOT/'scripts/release_native.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


class NativeReleaseTests(unittest.TestCase):
    def test_wrong_or_linked_archive_never_reaches_docker(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'archive';path.write_bytes(b'not accepted');link=Path(name)/'link';link.symlink_to(path)
            with patch.object(release,'run') as command:
                for candidate in (path,link,Path(name)/'missing'):
                    with self.assertRaises(ValueError):release.release(candidate,Path(name)/'receipt')
                command.assert_not_called()
    def test_frozen_archive_hash_is_checked_before_source_or_registry(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'archive';path.write_bytes(b'owned fixture')
            with patch.object(release,'ARCHIVE_SHA',sha256(path.read_bytes()).hexdigest()):release.verify_archive(path)
            path.write_bytes(b'changed fixture')
            with self.assertRaises(ValueError):release.verify_archive(path)
