"""Real dual/IPv6-only relay tests over Docker-published IPv6 sockets.

All containers use a private, internal IPv6 bridge. Synthetic public candidates
must map back to the exact local ULA, so media never leaves the test network.
Missing IPv6 support is a failure in the strict CI runner, never a skip.
"""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile
import time
import unittest

from test_container import run
from turn_wire import Client, attr, error

IMAGE = os.environ.get('LOCAL_AUDIO_TEST_IMAGE')


class IPv6Fixture:
    mode = None

    @classmethod
    def setUpClass(cls):
        cls.name = 'localaudio-' + cls.mode + '-' + secrets.token_hex(6)
        cls.network = cls.name + '-network'
        cls.password = secrets.token_urlsafe(36)
        cls.temp = tempfile.TemporaryDirectory(prefix='localaudio-ipv6-')
        folder = Path(cls.temp.name)
        folder.chmod(0o755)
        (folder / 'password').write_text(cls.password)
        (folder / 'password').chmod(0o444)  # Synthetic fixture secret only.
        cls.certificate = folder / 'cert.pem'
        key = folder / 'key.pem'
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key), '-out', str(cls.certificate), '-days', '2', '-subj', '/CN=relay.test', '-addext', 'subjectAltName=DNS:relay.test')
        cls.certificate.chmod(0o444)
        key.chmod(0o444)  # Synthetic fixture key only.
        # RFC4193-style random ULA network; no fabricated public Docker subnet.
        identifier = secrets.token_hex(5)
        subnet = 'fd' + identifier[:2] + ':' + identifier[2:6] + ':' + identifier[6:] + '::/64'
        cls.public6 = str(ipaddress.IPv6Address(sum(part << shift for part, shift in ((0x2001, 112), (0x4860, 96), (0x1234, 80), (1, 0)))))
        cls.public4 = '.'.join(str(x) for x in bytes([8]) * 4)
        try:
            run('docker', 'network', 'create', '--internal', '--ipv6', '--subnet', subnet, cls.network)
            args = ['docker', 'run', '-d', '--name', cls.name, '--network', cls.network, '--read-only', '--memory=512m', '--cpus=2', '--pids-limit=150', '--cap-drop=ALL', '--security-opt=no-new-privileges:true', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,mode=1777,size=16m']
            for protocol, port in (('udp', 21113), ('tcp', 21113), ('tcp', 5349)):
                args += ['-p', '[::1]::' + str(port) + '/' + protocol]
                if cls.mode == 'dual': args += ['-p', '127.0.0.1::' + str(port) + '/' + protocol]
            args += ['-v', str(folder) + ':/run/secrets:ro', '-e', 'TURN_IP_MODE=' + cls.mode, '-e', 'TURN_PUBLIC_IPV6=' + cls.public6, '-e', 'TURN_AUTH_MODE=static', '-e', 'TURN_USERNAME=fixture', '-e', 'TURN_PASSWORD_FILE=/run/secrets/password', '-e', 'TURN_REALM=relay.test', '-e', 'TURN_TLS_ENABLE=1', '-e', 'TURN_TLS_CERT_FILE=/run/secrets/cert.pem', '-e', 'TURN_TLS_KEY_FILE=/run/secrets/key.pem']
            if cls.mode == 'dual': args += ['-e', 'TURN_PUBLIC_IP=' + cls.public4]
            run(*args, IMAGE)
            for _ in range(60):
                if run('docker', 'exec', cls.name, '/opt/ts3-relay/healthcheck.sh', check=False).returncode == 0: break
                time.sleep(.25)
            else: raise RuntimeError('IPv6 fixture failed healthcheck for ' + cls.mode)
            cls.ports = {}
            for protocol, port, name in (('udp', 21113, 'udp'), ('tcp', 21113, 'tcp'), ('tcp', 5349, 'tls')):
                rows = run('docker', 'port', cls.name, str(port) + '/' + protocol).stdout.splitlines()
                cls.ports[name] = int(next(row for row in rows if row.startswith('[::1]:')).rsplit(':', 1)[1])
                if cls.mode == 'dual': cls.ports[name + '4'] = int(next(row for row in rows if row.startswith('127.0.0.1:')).rsplit(':', 1)[1])
            info = json.loads(run('docker', 'inspect', cls.name).stdout)[0]
            interface = info['NetworkSettings']['Networks'][cls.network]
            cls.relay6 = interface['GlobalIPv6Address']
            cls.relay4 = interface['IPAddress']
            if not ipaddress.ip_address(cls.relay6).is_private: raise RuntimeError('Fixture must use an actual ULA relay')
            network = json.loads(run('docker', 'network', 'inspect', cls.network).stdout)[0]
            if not network['Internal'] or not network['EnableIPv6']: raise RuntimeError('IPv6 fixture isolation is missing')
        except Exception:
            cls.cleanup_fixture()
            raise

    @classmethod
    def cleanup_fixture(cls):
        run('docker', 'rm', '-f', cls.name, check=False)
        run('docker', 'network', 'rm', cls.network, check=False)
        cls.temp.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls.cleanup_fixture()

    def client(self, transport='udp', family=6):
        c = Client(self.ports[transport + ('4' if family == 4 else '')], transport, trust_file=str(self.certificate), host='127.0.0.1' if family == 4 else '::1')
        self.addCleanup(c.close)
        return c

    def test_ipv6_authentication_udp_tcp_tls(self):
        for transport in ('udp', 'tcp', 'tls'):
            with self.subTest(transport=transport):
                c = self.client(transport)
                self.assertEqual(c.allocate('fixture', self.password, family=6)[0], 0x103)
                self.assertEqual(c.relay[0], self.public6)
                self.assertEqual(c.release()[0], 0x104)

    def test_ipv6_anonymous_unknown_wrong_rejected(self):
        for transport in ('udp', 'tcp', 'tls'):
            with self.subTest(transport=transport):
                c = self.client(transport)
                _, fields = c.exchange(3, attr(0x19, b'\x11\0\0\0') + attr(0x17, b'\x02\0\0\0'))
                self.assertEqual(error(fields), 401)
                for username, password in (('unknown-fixture', self.password), ('fixture', 'incorrect-test-password')):
                    c = self.client(transport)
                    self.assertEqual(error(c.allocate(username, password, family=6)[1]), 401)

    def test_ipv6_private_and_special_peers_rejected(self):
        c = self.client()
        self.assertEqual(c.allocate('fixture', self.password, family=6)[0], 0x103)
        other_ula = str(ipaddress.IPv6Address(int(ipaddress.IPv6Address(self.relay6)) + 100))
        special = [':'.join(format(word, 'x') for word in row) for row in ((0xfec0, 0, 0, 0, 0, 0, 0, 1), (0x64, 0xff9b, 0, 0, 0, 0, 0xa9fe, 0xa9fe), (0x64, 0xff9b, 1, 0, 0, 0, 0xa00, 1), (0x100, 0, 0, 1, 0, 0, 0, 1), (0x2002, 0xa00, 1, 0, 0, 0, 0, 0), (0x3ffe, 0, 0, 0, 0, 0, 0, 1), (0x3fff, 0, 0, 0, 0, 0, 0, 1), (0x5f00, 0, 0, 0, 0, 0, 0, 1))]
        targets = ('::', '::1', other_ula, 'fd00::1', 'fe80::1', 'ff02::1', '::ffff:7f00:1', '::ffff:a9fe:a9fe', '::ffff:a00:1', '100::1', '2001:db8::1', *special)
        for target in targets:
            with self.subTest(target=target):
                self.assertIn(error(c.permission(target)[1]), (403, 443))
        self.assertEqual(c.release()[0], 0x104)

    def test_ipv6_bidirectional_advertised_and_own_ula(self):
        for advertised in (True, False):
            with self.subTest(advertised=advertised):
                left, right = self.client(), self.client()
                for c in (left, right): self.assertEqual(c.allocate('fixture', self.password, family=6)[0], 0x103)
                target = self.public6 if advertised else self.relay6
                self.assertEqual(left.permission(target)[0], 0x108)
                self.assertEqual(right.permission(target)[0], 0x108)
                payload = b'LocalAudio IPv6 isolated relay ' + secrets.token_bytes(64)
                left.send_data(target, right.relay[1], payload)
                self.assertEqual(right.receive_data(), payload)
                right.send_data(target, left.relay[1], payload[::-1])
                self.assertEqual(left.receive_data(), payload[::-1])
                for c in (left, right): self.assertEqual(c.release()[0], 0x104)

    def test_default_family_ipv6_for_ipv6_transport(self):
        for transport in ('udp', 'tcp', 'tls'):
            c = self.client(transport)
            self.assertEqual(c.allocate('fixture', self.password, family=None)[0], 0x103)
            self.assertEqual(c.relay[0], self.public6)
            self.assertEqual(c.release()[0], 0x104)


@unittest.skipUnless(IMAGE, 'Set LOCAL_AUDIO_TEST_IMAGE to run isolated Docker integration tests')
class DualStack(IPv6Fixture, unittest.TestCase):
    mode = 'dual'

    def test_dual_stack_cross_family_and_ipv4_default_allocations(self):
        for transport in ('udp', 'tcp', 'tls'):
            for client_family, relay_family in ((4, 6), (6, 4), (4, None)):
                with self.subTest(transport=transport, client_family=client_family, relay_family=relay_family):
                    c = self.client(transport, client_family)
                    self.assertEqual(c.allocate('fixture', self.password, relay_family)[0], 0x103)
                    self.assertEqual(c.relay[0], self.public6 if relay_family == 6 else self.public4)
                    self.assertEqual(c.release()[0], 0x104)


@unittest.skipUnless(IMAGE, 'Set LOCAL_AUDIO_TEST_IMAGE to run isolated Docker integration tests')
class IPv6ServiceOnly(IPv6Fixture, unittest.TestCase):
    mode = 'ipv6'

    def test_ipv4_listener_and_relay_allocation_disabled(self):
        for transport in ('udp', 'tcp', 'tls'):
            c = self.client(transport)
            kind, fields = c.allocate('fixture', self.password, family=4)
            self.assertEqual(kind, 0x113)
            self.assertEqual(error(fields), 440)
        # Test the actual container IPv4 interface, not just absent host publish.
        self.assertTrue(self.relay4)
        with self.assertRaises(OSError):
            socket.create_connection((self.relay4, 21113), timeout=2)


if __name__ == '__main__':
    unittest.main()
