#!/usr/bin/env python3
"""Package tracked deployment sources and the tested image for offline use."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from check_publish import ROOT, findings


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package(image, output):
    image = Path(image)
    if image.is_symlink():
        raise ValueError('A regular tested image archive is required')
    image = image.resolve()
    output = Path(output).resolve()
    if not image.is_file() or image.is_symlink():
        raise ValueError('A regular tested image archive is required')
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Invalid release version')
    raw = subprocess.check_output(['git', 'ls-files', '--cached', '-z'], cwd=ROOT)
    sources = sorted({item.decode('utf-8') for item in raw.split(b'\0') if item})
    if not sources or not {'compose.yaml', '.env.example', 'scripts/deploy.sh', 'VERSION'} <= set(sources):
        raise ValueError('Tracked deployment sources are incomplete')
    snapshots = {}
    for relative in sources:
        path = ROOT / relative
        if findings(path):
            raise ValueError('Source boundary check failed: ' + relative)
        snapshots[relative] = path.read_bytes()
    image_hash = digest(image)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'LocalAudio-Server.zip'
    if archive.exists() or (output / 'SHA256SUMS.txt').exists():
        raise ValueError('A fresh release output directory is required')
    prefix = 'LocalAudio-Server/'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for relative, content in snapshots.items():
            bundle.writestr(prefix + relative, content)
        bundle.write(image, prefix + 'LocalAudio-Server.tar.gz', compress_type=zipfile.ZIP_STORED)
        bundle.writestr(prefix + 'LocalAudio-Server.tar.gz.sha256', image_hash + '  LocalAudio-Server.tar.gz\n')
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None or len(bundle.namelist()) != len(sources) + 2:
            raise ValueError('Archive verification failed')
        for relative, content in snapshots.items():
            if bundle.read(prefix + relative) != content:
                raise ValueError('Packaged source differs: ' + relative)
        with bundle.open(prefix + 'LocalAudio-Server.tar.gz') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != image_hash:
                raise ValueError('Packaged image differs from tested image')
    checksum = digest(archive)
    (output / 'SHA256SUMS.txt').write_text(checksum + '  LocalAudio-Server.zip\n', encoding='ascii')
    print(f'Packaged v{version}: {len(sources)} source files and tested image; SHA256 {checksum}')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python3 tools/package_release.py IMAGE.tar.gz OUTPUT_DIRECTORY')
    package(sys.argv[1], sys.argv[2])
