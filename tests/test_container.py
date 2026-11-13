import json,os,secrets,subprocess,tempfile,time,unittest
from pathlib import Path
from turn_wire import Client,attr,error
IMAGE=os.environ.get('LOCAL_AUDIO_TEST_IMAGE')
def run(*args,check=True):
    p=subprocess.run(args,capture_output=True,text=True,timeout=60)
    if check and p.returncode:raise RuntimeError('Fixture command failed: '+args[0]+' '+args[1])
    return p
@unittest.skipUnless(IMAGE,'Set LOCAL_AUDIO_TEST_IMAGE to run isolated Docker integration tests')
class Container(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='localaudio-test-'+secrets.token_hex(6);cls.password=secrets.token_urlsafe(36);cls.temp=tempfile.TemporaryDirectory(prefix='localaudio-docker-');folder=Path(cls.temp.name);folder.chmod(0o755)
        secret=folder/'password';secret.write_text(cls.password);secret.chmod(0o444) # synthetic test secret only
        cls.certificate=folder/'cert.pem';key=folder/'key.pem'
        run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cls.certificate),'-days','2','-subj','/CN=relay.test','-addext','subjectAltName=DNS:relay.test')
        cls.certificate.chmod(0o444);key.chmod(0o444) # synthetic local-fixture key only
        public='.'.join(str(x) for x in bytes([8])*4)
        try:
            run('docker','run','-d','--name',cls.name,'--read-only','--memory=512m','--cpus=2','--pids-limit=150','--cap-drop=ALL','--security-opt=no-new-privileges:true','--tmpfs','/tmp:rw,noexec,nosuid,nodev,mode=1777,size=16m','-p','127.0.0.1::21113/udp','-p','127.0.0.1::21113/tcp','-p','127.0.0.1::5349/tcp','-v',str(folder)+':/run/secrets:ro','-e','TURN_AUTH_MODE=static','-e','TURN_USERNAME=fixture','-e','TURN_PASSWORD_FILE=/run/secrets/password','-e','TURN_REALM=relay.test','-e','TURN_PUBLIC_IP='+public,'-e','TURN_TLS_ENABLE=1','-e','TURN_TLS_CERT_FILE=/run/secrets/cert.pem','-e','TURN_TLS_KEY_FILE=/run/secrets/key.pem',IMAGE)
            for _ in range(60):
                if run('docker','exec',cls.name,'/opt/ts3-relay/healthcheck.sh',check=False).returncode==0:break
                time.sleep(.25)
            else:raise RuntimeError('Isolated relay did not become healthy')
            cls.udp=int(run('docker','port',cls.name,'21113/udp').stdout.strip().rsplit(':',1)[1]);cls.tcp=int(run('docker','port',cls.name,'21113/tcp').stdout.strip().rsplit(':',1)[1]);cls.tls=int(run('docker','port',cls.name,'5349/tcp').stdout.strip().rsplit(':',1)[1])
            info=json.loads(run('docker','inspect',cls.name).stdout)[0];cls.relay_ip=next(iter(info['NetworkSettings']['Networks'].values()))['IPAddress']
        except Exception:
            run('docker','rm','-f',cls.name,check=False);cls.temp.cleanup();raise
    @classmethod
    def tearDownClass(cls):run('docker','rm','-f',cls.name,check=False);cls.temp.cleanup()
    def client(self,transport='udp'):
        c=Client({'udp':self.udp,'tcp':self.tcp,'tls':self.tls}[transport],transport,trust_file=str(self.certificate));self.addCleanup(c.close);return c
    def test_authenticated_udp_and_tcp(self):
        for transport in ('udp','tcp','tls'):
            with self.subTest(transport=transport):
                c=self.client(transport);kind,_=c.allocate('fixture',self.password);self.assertEqual(kind,0x103);self.assertEqual(c.release()[0],0x104)
    def test_anonymous_and_wrong_password_are_rejected(self):
        for transport in ('udp','tcp','tls'):
            with self.subTest(transport=transport):
                c=self.client(transport);_,fields=c.exchange(3,attr(0x19,b'\x11\0\0\0'));self.assertEqual(error(fields),401)
                c=self.client(transport);_,fields=c.allocate('fixture','incorrect-test-password');self.assertEqual(error(fields),401)
    def test_private_and_metadata_permissions_are_rejected(self):
        c=self.client();self.assertEqual(c.allocate('fixture',self.password)[0],0x103)
        for ip in ('0.0.0.0','127.0.0.1','169.254.169.254','10.20.30.40','172.16.0.1','192.168.1.1','.'.join(map(str,(192,88,99,1)))):
            self.assertEqual(error(c.permission(ip)[1]),403)
        c.release()
    def test_nonroot_and_no_password_in_logs_or_environment(self):
        info=json.loads(run('docker','inspect',self.name).stdout)[0];self.assertEqual(info['Config']['User'],'65534:65534');self.assertTrue(info['HostConfig']['ReadonlyRootfs']);self.assertIn('ALL',info['HostConfig']['CapDrop'])
        self.assertNotIn(self.password,'\n'.join(info['Config']['Env']));logs=run('docker','logs',self.name);self.assertNotIn(self.password,logs.stdout+logs.stderr)
        self.assertEqual(info['HostConfig']['Memory'],512*1024*1024);self.assertEqual(info['HostConfig']['NanoCpus'],2000000000);self.assertEqual(info['HostConfig']['PidsLimit'],150)
    def test_actual_bidirectional_same_server_udp_relay(self):
        left=self.client();right=self.client()
        self.assertEqual(left.allocate('fixture',self.password)[0],0x103)
        self.assertEqual(right.allocate('fixture',self.password)[0],0x103)
        # Use the verified container interface instead of the synthetic public
        # address. Every media datagram stays inside this test container.
        self.assertEqual(left.permission(self.relay_ip)[0],0x108)
        self.assertEqual(right.permission(self.relay_ip)[0],0x108)
        payload=b'LocalAudio isolated relay '+secrets.token_bytes(32)
        left.send_data(self.relay_ip,right.relay[1],payload)
        self.assertEqual(right.receive_data(),payload)
        right.send_data(self.relay_ip,left.relay[1],payload[::-1])
        self.assertEqual(left.receive_data(),payload[::-1])
        self.assertEqual(left.release()[0],0x104)
        self.assertEqual(right.release()[0],0x104)
    def test_runtime_version_and_unused_database_clients_are_absent(self):
        version=run('docker','exec',self.name,'/usr/bin/turnserver','--version').stdout
        self.assertIn('4.18.0',version)
        dependencies=run('docker','exec',self.name,'ldd','/usr/bin/turnserver').stdout.lower()
        for name in ('libpq','mariadb','mysql','mongoc','bson','hiredis','lmdb'):
            self.assertNotIn(name,dependencies)

if __name__=='__main__':unittest.main()
