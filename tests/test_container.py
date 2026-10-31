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
        public='.'.join(str(x) for x in bytes([8])*4)
        try:
            run('docker','run','-d','--name',cls.name,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true','--tmpfs','/tmp:rw,noexec,nosuid,nodev,mode=1777,size=16m','-p','127.0.0.1::21113/udp','-p','127.0.0.1::21113/tcp','-v',str(secret)+':/run/secrets/test-password:ro','-e','TURN_AUTH_MODE=static','-e','TURN_USERNAME=fixture','-e','TURN_PASSWORD_FILE=/run/secrets/test-password','-e','TURN_REALM=relay.test','-e','TURN_PUBLIC_IP='+public,IMAGE)
            for _ in range(60):
                if run('docker','exec',cls.name,'/opt/ts3-relay/healthcheck.sh',check=False).returncode==0:break
                time.sleep(.25)
            else:raise RuntimeError('Isolated relay did not become healthy')
            cls.udp=int(run('docker','port',cls.name,'21113/udp').stdout.strip().rsplit(':',1)[1]);cls.tcp=int(run('docker','port',cls.name,'21113/tcp').stdout.strip().rsplit(':',1)[1])
        except Exception:
            run('docker','rm','-f',cls.name,check=False);cls.temp.cleanup();raise
    @classmethod
    def tearDownClass(cls):run('docker','rm','-f',cls.name,check=False);cls.temp.cleanup()
    def client(self,transport='udp'):
        c=Client(self.udp if transport=='udp' else self.tcp,transport);self.addCleanup(c.close);return c
    def test_authenticated_udp_and_tcp(self):
        for transport in ('udp','tcp'):
            with self.subTest(transport=transport):
                c=self.client(transport);kind,_=c.allocate('fixture',self.password);self.assertEqual(kind,0x103);self.assertEqual(c.release()[0],0x104)
    def test_anonymous_and_wrong_password_are_rejected(self):
        c=self.client();_,fields=c.exchange(3,attr(0x19,b'\x11\0\0\0'));self.assertEqual(error(fields),401)
        c=self.client();_,fields=c.allocate('fixture','incorrect-test-password');self.assertEqual(error(fields),401)
    def test_private_and_metadata_permissions_are_rejected(self):
        c=self.client();self.assertEqual(c.allocate('fixture',self.password)[0],0x103)
        for ip in ('127.0.0.1','169.254.169.254','10.20.30.40'):
            self.assertEqual(error(c.permission(ip)[1]),403)
        c.release()
    def test_nonroot_and_no_password_in_logs_or_environment(self):
        info=json.loads(run('docker','inspect',self.name).stdout)[0];self.assertEqual(info['Config']['User'],'65534:65534');self.assertTrue(info['HostConfig']['ReadonlyRootfs']);self.assertIn('ALL',info['HostConfig']['CapDrop'])
        self.assertNotIn(self.password,'\n'.join(info['Config']['Env']));self.assertNotIn(self.password,run('docker','logs',self.name).stdout)
if __name__=='__main__':unittest.main()
