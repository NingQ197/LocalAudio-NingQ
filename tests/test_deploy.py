"""Exercise deployment decisions without running Docker or changing ownership."""
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import tempfile
import unittest

from test_entrypoint import ROOT, SHELL, posix


@unittest.skipUnless(SHELL, 'POSIX-compatible shell is required')
class Deployment(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='localaudio-deploy-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        scripts = self.root / 'scripts'
        scripts.mkdir()
        self.log = self.root / 'docker-calls'
        (self.root / '.env').write_text('TURN_REALM=relay.test\n')
        (self.root / 'secrets').mkdir()
        (self.root / 'secrets/turn-password').write_text(secrets.token_urlsafe(36))
        text = (ROOT / 'scripts/deploy.sh').read_text()
        text = text.replace('set -eu\n', 'set -eu\nPATH=' + shlex.quote(posix(self.bin)) + ':"$PATH"\nexport PATH\n', 1)
        self.script = scripts / 'deploy.sh'
        self.script.write_text(text, encoding='utf-8', newline='\n')
        self.wrapper('id', "printf '0\\n'\n")
        self.wrapper('chown', 'exit 0\n')
        self.wrapper('chmod', 'exit 0\n')
        self.wrapper('python3', 'exec ' + shlex.quote(posix(Path(sys.executable))) + ' "$@"\n')
        self.wrapper('docker', '''printf '%s\\n' "$*" >>"$FIXTURE_LOG"
case "$*" in
  *'config --format json') printf '%s\\n' "$FIXTURE_CONFIG" ;;
esac
''')

    def wrapper(self, name, body):
        file = self.bin / name
        file.write_text('#!/bin/sh\n' + body, encoding='utf-8', newline='\n')
        file.chmod(0o755)

    def run_deploy(self, tls='0', args=()):
        env = os.environ.copy()
        env.update(FIXTURE_LOG=posix(self.log), FIXTURE_CONFIG=json.dumps({'services': {'turn': {'environment': {'TURN_TLS_ENABLE': tls}}}}))
        p = subprocess.run([SHELL, str(self.script), *args], env=env, capture_output=True, text=True, timeout=15)
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return p, lines

    def test_tls_enables_port_override_for_every_deployment_command(self):
        p, lines = self.run_deploy('1')
        self.assertEqual(p.returncode, 0, p.stderr)
        deployment = [line for line in lines if any(word in line for word in ('build turn', 'run --rm', 'up -d', 'ps turn'))]
        self.assertEqual(len(deployment), 4)
        self.assertTrue(all('-f compose.yaml -f compose.tls.yaml' in line for line in deployment))

    def test_no_build_uses_loaded_image_and_preserves_credentials(self):
        before = (self.root / 'secrets/turn-password').read_bytes()
        p, lines = self.run_deploy(args=('--no-build',))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(any('build turn' in line for line in lines))
        self.assertTrue(any('up -d --no-build' in line for line in lines))
        self.assertFalse(any('compose.tls.yaml' in line for line in lines))
        self.assertEqual(before, (self.root / 'secrets/turn-password').read_bytes())

    def test_invalid_tls_value_prevents_startup(self):
        p, lines = self.run_deploy('enabled')
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(any('up -d' in line for line in lines))

    def test_password_directory_and_unsupported_arguments_are_rejected(self):
        password = self.root / 'secrets/turn-password'
        password.unlink()
        password.mkdir()
        p, _ = self.run_deploy()
        self.assertEqual(p.returncode, 64)
        self.assertIn('regular file', p.stderr)
        p, _ = self.run_deploy(args=('--no-auth',))
        self.assertEqual(p.returncode, 64)


if __name__ == '__main__':
    unittest.main()
