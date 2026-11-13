import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publish_check', ROOT / 'tools/check_publish.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@unittest.skipUnless(shutil.which('git'), 'Git is required')
class PublishBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='localaudio-publish-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        (self.root / 'README.md').write_text('Safe fixture\n')
        subprocess.run(['git', '-C', str(self.root), 'add', 'README.md'], check=True, capture_output=True)
        self.previous = check.ROOT
        check.ROOT = self.root
        self.addCleanup(setattr, check, 'ROOT', self.previous)

    def test_untracked_sensitive_file_is_not_hidden_by_existing_index(self):
        file = self.root / 'accidental.txt'
        file.write_text('-' * 5 + 'BEGIN PRIVATE KEY' + '-' * 5 + '\nsynthetic fixture\n')
        self.assertIn(file, check.paths())
        self.assertIn('private_key', check.findings(file))

    def test_new_document_and_invalid_encoding_are_checked(self):
        file = self.root / 'NEW.md'
        file.write_text('A new source document\n')
        self.assertIn(file, check.paths())
        self.assertEqual(check.findings(file), [])
        file.write_bytes(b'\xff')
        self.assertIn('non_utf8_source_file', check.findings(file))

    def test_runtime_and_deleted_tracked_files_fail_closed(self):
        file = self.root / 'credentials.key'
        file.write_text('Synthetic fixture')
        self.assertIn('runtime_or_binary_file', check.findings(file))
        tracked = self.root / 'README.md'
        tracked.unlink()
        self.assertIn('missing_or_nonregular_source_file', check.findings(tracked))


if __name__ == '__main__':
    unittest.main()
