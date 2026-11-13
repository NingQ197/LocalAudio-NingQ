"""Local parser, healthcheck and RFC wire checks; no network is contacted."""
import ipaddress
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile
import unittest

from test_entrypoint import ROOT, SHELL, posix
from turn_wire import decode_address, peer_address


def words6(*words):
    return ':'.join(format(word, 'x') for word in words)


@unittest.skipUnless(SHELL, 'POSIX-compatible shell is required')
class IPv6Parser(unittest.TestCase):
    def parse(self, address, role='normalize'):
        command = 'awk -v value=' + shlex.quote(address) + ' -v role=' + shlex.quote(role) + ' -f ' + shlex.quote(posix(ROOT / 'server/ipv6.awk'))
        return subprocess.run([SHELL, '-c', command], capture_output=True, text=True, timeout=10)

    def test_normalization_matches_standard_library(self):
        addresses = ['::', '::1', 'FD42:2111:3000::2', '2001:db8::123', 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff']
        rng = random.Random(6156)
        addresses += [str(ipaddress.IPv6Address(rng.getrandbits(128))) for _ in range(32)]
        for address in addresses:
            with self.subTest(address=address):
                p = self.parse(address)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout.strip(), ipaddress.IPv6Address(address).exploded)

    def test_invalid_syntax_and_non_bare_addresses_are_rejected(self):
        for address in ('', ':', '1:2:3:4:5:6:7', '1:2:3:4:5:6:7:8:9', '1::2::3', '1:::2', ':1:2:3:4:5:6:7', '1:2:3:4:5:6:7:', '10000::', 'gg::1', '::ffff:127.0.0.1', '[::1]', 'fe80::1%eth0', 'fd00::/64', '::1\nno-auth'):
            with self.subTest(address=address):
                self.assertNotEqual(self.parse(address).returncode, 0)

    def test_public_and_relay_address_policy(self):
        public = ':'.join(format(x, 'x') for x in (0x2001, 0x4860, 0, 1, 0, 0, 0, 1))
        self.assertEqual(self.parse(public, 'public').returncode, 0)
        self.assertEqual(self.parse(public, 'relay').returncode, 0)
        self.assertEqual(self.parse('fd42:2111:3000::2', 'relay').returncode, 0)
        special = [words6(*row) for row in ((0x64, 0xff9b, 0, 0, 0, 0, 0xa00, 1), (0x100, 0, 0, 1, 0, 0, 0, 1), (0x2002, 0, 0, 0, 0, 0, 0, 1), (0x3ffe, 0, 0, 0, 0, 0, 0, 1), (0x3fff, 0, 0, 0, 0, 0, 0, 1), (0x5f00, 0, 0, 0, 0, 0, 0, 1), (0xfec0, 0, 0, 0, 0, 0, 0, 1))]
        for address in ('::', '::1', '::ffff:7f00:1', '100::1', '2001::1', '2001:1ff::1', '2001:db8::1', 'fd42:2111:3000::2', 'fe80::1', 'ff02::1', *special):
            with self.subTest(address=address):
                self.assertNotEqual(self.parse(address, 'public').returncode, 0)
                if not address.startswith('fd42:'):
                    self.assertNotEqual(self.parse(address, 'relay').returncode, 0)


@unittest.skipUnless(SHELL, 'POSIX-compatible shell is required')
class Healthcheck(unittest.TestCase):
    def test_mode_specific_probe_and_failure(self):
        with tempfile.TemporaryDirectory(prefix='localaudio-health-') as temporary:
            folder = Path(temporary)
            log = folder / 'calls'
            fake = folder / 'probe'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>"$FIXTURE_LOG"\n[ "${FIXTURE_FAIL:-}" != "$3" ]\n', newline='\n')
            fake.chmod(0o755)
            script = folder / 'healthcheck.sh'
            script.write_text((ROOT / 'server/healthcheck.sh').read_text().replace('/usr/bin/turnutils_stunclient', shlex.quote(posix(fake))), newline='\n')
            for mode, targets in (('ipv4', ['127.0.0.1']), ('dual', ['127.0.0.1', '::1']), ('ipv6', ['::1'])):
                env = os.environ.copy()
                env.update(TURN_IP_MODE=mode, FIXTURE_LOG=posix(log), TURN_PORT='21113')
                if log.exists(): log.unlink()
                p = subprocess.run([SHELL, str(script)], env=env, capture_output=True, timeout=10)
                self.assertEqual(p.returncode, 0)
                self.assertEqual(log.read_text().splitlines(), ['-p 21113 ' + target for target in targets])
                env['FIXTURE_FAIL'] = targets[-1]
                self.assertNotEqual(subprocess.run([SHELL, str(script)], env=env, capture_output=True, timeout=10).returncode, 0)
            env['TURN_IP_MODE'] = 'invalid'
            self.assertNotEqual(subprocess.run([SHELL, str(script)], env=env, capture_output=True, timeout=10).returncode, 0)


class WireIPv6(unittest.TestCase):
    def test_official_rfc5769_ipv6_xor_vector(self):
        # RFC5769 section 2.3: transaction and XOR-MAPPED-ADDRESS bytes.
        transaction = bytes.fromhex('b7e7a701bc34d686fa87dfae')
        encoded = bytes.fromhex('0002a1470113a9faa5d3f179bc25f4b5bed2b9d9')
        expected = ('2001:db8:1234:5678:11:2233:4455:6677', 32853)
        self.assertEqual(decode_address(encoded, transaction), expected)
        self.assertEqual(peer_address(*expected, transaction), encoded)
        for invalid in (None, b'', b'x' * 11, b'x' * 13):
            with self.assertRaises(ValueError): decode_address(encoded, invalid)
            with self.assertRaises(ValueError): peer_address(*expected, invalid)


if __name__ == '__main__':
    unittest.main()
