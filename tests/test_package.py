"""Check the offline package boundary and nested image checksum."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import check_publish
import package_release


@unittest.skipUnless(shutil.which('git'), 'Git is required')
class OfflinePackage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='localaudio-package-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'source'
        self.source.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True, capture_output=True)
        for relative, content in {
            'VERSION': '2.1.0\n', 'compose.yaml': 'services: {}\n',
            '.env.example': 'TURN_REALM=relay.example.com\n',
            'scripts/deploy.sh': '#!/bin/sh\nexit 0\n',
        }.items():
            file = self.source / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding='utf-8')
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True, capture_output=True)
        self.image = self.folder / 'tested.tar.gz'
        self.image.write_bytes(b'synthetic-tested-image\0')
        self.output = self.folder / 'output'
        for module in (check_publish, package_release):
            old = module.ROOT
            module.ROOT = self.source
            self.addCleanup(setattr, module, 'ROOT', old)

    def test_package_contains_exact_image_and_tracked_sources_only(self):
        (self.source / '.env').write_text('synthetic-private-runtime-setting\n')
        package_release.package(self.image, self.output)
        archive = self.output / 'LocalAudio-Server.zip'
        self.assertEqual((self.output / 'SHA256SUMS.txt').read_text(), hashlib.sha256(archive.read_bytes()).hexdigest() + '  LocalAudio-Server.zip\n')
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(len(bundle.namelist()), 6)
            self.assertFalse(any(name.endswith('/.env') for name in bundle.namelist()))
            self.assertEqual(bundle.read('LocalAudio-Server/LocalAudio-Server.tar.gz'), self.image.read_bytes())
            self.assertEqual(bundle.read('LocalAudio-Server/LocalAudio-Server.tar.gz.sha256').decode(), hashlib.sha256(self.image.read_bytes()).hexdigest() + '  LocalAudio-Server.tar.gz\n')

    def test_tracked_private_runtime_is_rejected(self):
        (self.source / '.env').write_text('synthetic-private-runtime-setting\n')
        subprocess.run(['git', '-C', str(self.source), 'add', '.env'], check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, 'Source boundary check failed'):
            package_release.package(self.image, self.output)

    def test_existing_package_is_not_overwritten(self):
        package_release.package(self.image, self.output)
        original = (self.output / 'LocalAudio-Server.zip').read_bytes()
        with self.assertRaisesRegex(ValueError, 'fresh release output'):
            package_release.package(self.image, self.output)
        self.assertEqual((self.output / 'LocalAudio-Server.zip').read_bytes(), original)

    def test_image_symlink_is_rejected(self):
        alias = self.folder / 'alias.tar.gz'
        try:
            alias.symlink_to(self.image)
        except OSError:
            self.skipTest('File symlinks are unavailable')
        with self.assertRaisesRegex(ValueError, 'regular tested image'):
            package_release.package(alias, self.output)


if __name__ == '__main__':
    unittest.main()
