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
        if os.name == 'nt':
            # Native Windows Python cannot exec a POSIX shell-script shim.
            text = text.replace('["docker",', '[' + json.dumps(str(SHELL).replace('\\', '/')) + ',' + json.dumps((self.bin / 'docker').as_posix()) + ',')
        self.script = scripts / 'deploy.sh'
        self.script.write_text(text, encoding='utf-8', newline='\n')
        self.wrapper('id', "printf '0\\n'\n")
        self.wrapper('chown', 'exit 0\n')
        self.wrapper('chmod', 'exit 0\n')
        self.wrapper('python3', 'exec ' + shlex.quote(posix(Path(sys.executable))) + ' "$@"\n')
        self.wrapper('docker', '''printf '%s\\n' "$*" >>"$FIXTURE_LOG"
case "$*" in *'build turn') [ "${FIXTURE_BUILD_FAIL:-0}" != 1 ] || exit 1;; esac
case "$*" in
  *'config --format json') printf '%s\\n' "$FIXTURE_CONFIG" ;;
  'network inspect '*) printf '%s\\n' "${FIXTURE_NETWORK:-[]}" ;;
  'inspect '*) printf '%s\\n' "${FIXTURE_CONTAINER:-[]}" ;;
esac
''')

    def wrapper(self, name, body):
        file = self.bin / name
        file.write_text('#!/bin/sh\n' + body, encoding='utf-8', newline='\n')
        file.chmod(0o755)

    def run_deploy(self, tls='0', args=(), mode='ipv4', public4=None, network=None, container=None, build_fail=False):
        env = os.environ.copy()
        settings={'TURN_TLS_ENABLE':tls,'TURN_IP_MODE':mode,'TURN_REALM':'relay.test','TURN_PUBLIC_IP':public4 if public4 is not None else '.'.join(str(x) for x in bytes([8])*4),'TURN_PUBLIC_IPV6':':'.join(format(x,'x') for x in (0x2001,0x4860,0,1,0,0,0,1))}
        env.update(FIXTURE_LOG=posix(self.log), FIXTURE_CONFIG=json.dumps({'name':'localaudio-ningq','services': {'turn': {'environment': settings}},'networks':{'default':{'name':'localaudio-ningq_default','ipam':{'config':[{'subnet':'fd42:2111:3000::/64'}]}}}}),FIXTURE_NETWORK=json.dumps(network or []),FIXTURE_CONTAINER=json.dumps(container or []))
        env['FIXTURE_BUILD_FAIL'] = '1' if build_fail else '0'
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


    def test_dual_and_ipv6_only_compose_selection(self):
        for mode in ('dual','ipv6'):
            with self.subTest(mode=mode):
                p,lines=self.run_deploy('1',args=('--no-build',),mode=mode,public4='REPLACE_WITH_PUBLIC_IPV4' if mode=='ipv6' else None)
                self.assertEqual(p.returncode,0,p.stderr)
                deployment=[line for line in lines if 'up -d' in line][-1]
                self.assertIn('-f compose.ipv6.yaml',deployment)
                self.assertIn('-f compose.tls.ipv6.yaml',deployment)
                self.assertEqual('-f compose.ipv6only.yaml' in deployment,mode=='ipv6')
                self.assertEqual('-f compose.tls.yaml' in deployment,mode=='dual')
    def test_invalid_ip_mode_prevents_deployment(self):
        p,lines=self.run_deploy(mode='mixed')
        self.assertNotEqual(p.returncode,0)
        self.assertFalse(any('up -d' in line for line in lines))

    def test_ipv4_to_ipv6_recreates_only_owned_relay_network(self):
        network={'EnableIPv6':False,'Labels':{'com.docker.compose.project':'localaudio-ningq'},'IPAM':{'Config':[]},'Containers':{}}
        p,lines=self.run_deploy(mode='dual',network=[network],args=('--no-build',))
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertTrue(any('stop turn' in line for line in lines))
        self.assertIn('network rm localaudio-ningq_default',lines)
    def test_network_with_other_services_is_never_replaced(self):
        network={'EnableIPv6':False,'Labels':{'com.docker.compose.project':'localaudio-ningq'},'IPAM':{'Config':[]},'Containers':{'fixture':{}}}
        container={'Config':{'Labels':{'com.docker.compose.project':'other','com.docker.compose.service':'turn'}}}
        p,lines=self.run_deploy(mode='dual',network=[network],container=[container])
        self.assertNotEqual(p.returncode,0)
        self.assertFalse(any('stop turn' in line or 'network rm' in line for line in lines))

    def test_network_owner_is_checked_even_when_ipv6_already_matches(self):
        network={'EnableIPv6':True,'Labels':None,'IPAM':{'Config':[{'Subnet':'fd42:2111:3000::/64'}]},'Containers':{}}
        p,lines=self.run_deploy(mode='dual',network=[network],args=('--no-build',))
        self.assertNotEqual(p.returncode,0)
        self.assertIn('outside this Compose project',p.stderr)
        self.assertFalse(any('up -d' in line for line in lines))

    def test_oneoff_container_prevents_network_replacement(self):
        network={'EnableIPv6':False,'Labels':{'com.docker.compose.project':'localaudio-ningq'},'IPAM':{'Config':[]},'Containers':{'fixture':{}}}
        container={'Config':{'Labels':{'com.docker.compose.project':'localaudio-ningq','com.docker.compose.service':'turn','com.docker.compose.oneoff':'True'}}}
        p,lines=self.run_deploy(mode='dual',network=[network],container=[container],args=('--no-build',))
        self.assertNotEqual(p.returncode,0)
        self.assertFalse(any('stop turn' in line or 'network rm' in line for line in lines))

    def test_build_failure_does_not_interrupt_existing_relay(self):
        network={'EnableIPv6':False,'Labels':{'com.docker.compose.project':'localaudio-ningq'},'IPAM':{'Config':[]},'Containers':{}}
        p,lines=self.run_deploy(mode='dual',network=[network],build_fail=True)
        self.assertNotEqual(p.returncode,0)
        self.assertTrue(any('build turn' in line for line in lines))
        self.assertFalse(any('stop turn' in line or 'network rm' in line for line in lines))

if __name__ == '__main__':
    unittest.main()
