import os
import secrets
import shutil
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SHELL=shutil.which('sh') or ('C:/Program Files/Git/bin/bash.exe' if os.name=='nt' else None)
def posix(path):
    text=path.resolve().as_posix()
    return '/'+text[0].lower()+text[2:] if len(text)>2 and text[1]==':' else text

@unittest.skipUnless(SHELL,'POSIX-compatible shell is required')
class Entrypoint(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='localaudio-check-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.bin=self.root/'bin';self.bin.mkdir();host=self.bin/'hostname';host.write_text("#!/bin/sh\nprintf '172.29.0.2 127.0.0.1 fd42:2111:3000::2 fe80::2 ::1\\n'\n");host.chmod(0o755)
        self.password=secrets.token_urlsafe(36)
        self.env=os.environ.copy();self.env['PATH']=str(self.bin)+os.pathsep+self.env['PATH']
        for key in list(self.env):
            if key.startswith('TURN_'):del self.env[key]
        # Synthetic validation-only address: the test never sends traffic to it.
        self.env.update(TURN_REALM='relay.test',TURN_PUBLIC_IP='.'.join(str(x) for x in bytes([8])*4),TURN_AUTH_MODE='static',TURN_USERNAME='fixture',TURN_PASSWORD=self.password)
        self.script=self.root/'entrypoint.sh';self.runtime=self.root/'runtime'
        text=(ROOT/'server/entrypoint.sh').read_text()
        text=text.replace('set -eu\n','set -eu\nPATH='+shlex.quote(posix(self.bin))+':"$PATH"\nexport PATH\n',1)
        text=text.replace('/tmp/ts3-turn',posix(self.runtime)).replace('/opt/ts3-relay/denied-peers.conf',posix(ROOT/'server/denied-peers.conf')).replace('/opt/ts3-relay/ipv6.awk',posix(ROOT/'server/ipv6.awk'))
        self.script.write_text(text,encoding='utf-8',newline='\n')
    def run_script(self,changes=None,args=('--validate-only',)):
        env=self.env.copy()
        for key,value in (changes or {}).items():
            if value is None:env.pop(key,None)
            else:env[key]=value
        return subprocess.run([SHELL,str(self.script),*args],env=env,capture_output=True,text=True,timeout=10)
    def test_static_config_and_secret_redaction(self):
        p=self.run_script();self.assertEqual(p.returncode,0,p.stderr);self.assertNotIn(self.password,p.stdout+p.stderr)
        text=(self.runtime/'turnserver.conf').read_text();self.assertIn('lt-cred-mech\n',text);self.assertIn('user=fixture:'+self.password,text);self.assertNotIn('\nno-auth\n',text);self.assertNotIn('userdb=',text)
    def test_file_password(self):
        f=self.root/'credential';f.write_text(self.password+'\n');p=self.run_script({'TURN_PASSWORD':None,'TURN_PASSWORD_FILE':posix(f)});self.assertEqual(p.returncode,0,p.stderr)
    def test_rejects_invalid_inputs(self):
        cases=[{'TURN_PASSWORD':None},{'TURN_PASSWORD':'x'*40},{'TURN_PASSWORD':None,'TURN_PASSWORD_FILE':posix(self.root)},{'TURN_PASSWORD':self.password+'\nno-auth'}, {'TURN_AUTH_MODE':'anonymous'}, {'TURN_USERNAME':'x:password'}, {'TURN_USERNAME':'x\nno-auth'}, {'TURN_REALM':'x\nno-auth'}, {'TURN_REALM':'bad..realm'}, {'TURN_PUBLIC_IP':'127.0.0.1'}, {'TURN_PUBLIC_IP':'.'.join(map(str,(192,88,99,1)))}, {'TURN_PUBLIC_IP':'203.0.113.10'}, {'TURN_PUBLIC_IP':'01.2.3.4'}, {'TURN_PUBLIC_IP':self.env['TURN_PUBLIC_IP']+'\nno-auth'}, {'TURN_PORT':'021113'}, {'TURN_PORT':'65536'}, {'TURN_PORT':'49161'}, {'TURN_TLS_PORT':'49161'}, {'TURN_MIN_PORT':'50000','TURN_MAX_PORT':'40000'}, {'TURN_USER_QUOTA':'0'}, {'TURN_TOTAL_QUOTA':'-1'}, {'TURN_RELAY_IP':'10.99.98.97'}, {'TURN_TLS_ENABLE':'maybe'}, {'TURN_TLS_ENABLE':'1'}, {'TURN_SHARED_SECRET':secrets.token_urlsafe(40)}]
        for changes in cases:
            with self.subTest(fields=sorted(changes)):
                p=self.run_script(changes);self.assertEqual(p.returncode,64);self.assertNotIn(self.password,p.stdout+p.stderr)
    def test_rejects_arbitrary_command_flags(self):
        self.assertEqual(self.run_script(args=('--no-auth',)).returncode,64)
    def test_secret_auth_remains_optional(self):
        p=self.run_script({'TURN_AUTH_MODE':'secret','TURN_USERNAME':None,'TURN_PASSWORD':None,'TURN_SHARED_SECRET':secrets.token_urlsafe(40)})
        self.assertEqual(p.returncode,0,p.stderr)
    def test_config_limits_and_same_server_exception(self):
        self.assertEqual(self.run_script().returncode,0)
        text=(self.runtime/'turnserver.conf').read_text();self.assertIn('user-quota=16\n',text);self.assertIn('total-quota=128\n',text);self.assertIn('allowed-peer-ip=172.29.0.2\n',text);self.assertIn('denied-peer-ip=169.254.0.0-',text);self.assertNotIn('denied-peer-ip=::\n',text)

    def tls_fixture(self, name):
        key=self.root/(name+'.key');cert=self.root/(name+'.pem')
        command='openssl req -x509 -newkey rsa:2048 -nodes -keyout '+shlex.quote(key.resolve().as_posix())+' -out '+shlex.quote(cert.resolve().as_posix())+' -days 2 -subj /CN=relay.test'
        env=os.environ.copy();env['MSYS_NO_PATHCONV']='1'
        p=subprocess.run([SHELL,'-c',command],env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,'Fixture certificate generation failed')
        return cert,key
    def test_tls_valid_pair_and_wrong_private_key(self):
        cert,key=self.tls_fixture('valid');_,other=self.tls_fixture('other')
        values={'TURN_TLS_ENABLE':'1','TURN_TLS_CERT_FILE':posix(cert),'TURN_TLS_KEY_FILE':posix(key)}
        p=self.run_script(values);self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn(self.password,p.stdout+p.stderr)
        self.assertFalse((self.runtime/'key-public.der').exists())
        values['TURN_TLS_KEY_FILE']=posix(other)
        p=self.run_script(values);self.assertEqual(p.returncode,64)
        self.assertIn('do not match',p.stderr)
    def test_tls_invalid_private_key_fails_closed(self):
        cert,key=self.tls_fixture('valid');key.write_text('invalid synthetic key')
        p=self.run_script({'TURN_TLS_ENABLE':'1','TURN_TLS_CERT_FILE':posix(cert),'TURN_TLS_KEY_FILE':posix(key)})
        self.assertEqual(p.returncode,64);self.assertIn('private key is invalid',p.stderr)
    def test_shared_secret_file_must_be_regular(self):
        p=self.run_script({'TURN_AUTH_MODE':'secret','TURN_USERNAME':None,'TURN_PASSWORD':None,'TURN_SHARED_SECRET_FILE':posix(self.root)})
        self.assertEqual(p.returncode,64)

    def test_ipv6_only_does_not_require_ipv4_and_binds_concrete_listeners(self):
        public=':'.join(format(x,'x') for x in (0x2001,0x4860,0,1,0,0,0,1))
        p=self.run_script({'TURN_IP_MODE':'ipv6','TURN_PUBLIC_IP':None,'TURN_PUBLIC_IPV6':public,'TURN_RELAY_IPV6':'FD42:2111:3000:0:0:0:0:2'})
        self.assertEqual(p.returncode,0,p.stderr)
        text=(self.runtime/'turnserver.conf').read_text()
        self.assertNotIn('listening-ip=0.0.0.0',text)
        self.assertNotIn('listening-ip=::\n',text)
        self.assertIn('listening-ip=::1\n',text)
        self.assertIn('allowed-peer-ip=fd42:2111:3000:0000:0000:0000:0000:0002\n',text)
        self.assertIn('allocation-default-address-family=ipv6\n',text)
    def test_dual_stack_requires_both_public_addresses(self):
        public=':'.join(format(x,'x') for x in (0x2001,0x4860,0,1,0,0,0,1))
        self.assertEqual(self.run_script({'TURN_IP_MODE':'dual','TURN_PUBLIC_IPV6':public}).returncode,0)
        text=(self.runtime/'turnserver.conf').read_text()
        self.assertEqual(text.count('allowed-peer-ip='),2)
        self.assertIn('allocation-default-address-family=keep\n',text)
        for values in ({'TURN_IP_MODE':'dual'}, {'TURN_IP_MODE':'dual','TURN_PUBLIC_IPV6':public,'TURN_PUBLIC_IP':None}, {'TURN_IP_MODE':'bad'}, {'TURN_IP_MODE':'ipv6','TURN_PUBLIC_IPV6':'2001:db8::1'}, {'TURN_IP_MODE':'ipv6','TURN_PUBLIC_IPV6':public,'TURN_RELAY_IPV6':'fd42:2111:3000::3'}, {'TURN_IP_MODE':'ipv6','TURN_PUBLIC_IPV6':public,'TURN_RELAY_IPV6':'fe80::2'}):
            with self.subTest(values=values):self.assertEqual(self.run_script(values).returncode,64)

if __name__=='__main__':unittest.main()
