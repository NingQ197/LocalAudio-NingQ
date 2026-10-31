"""Small local-fixture TURN client; no production endpoint is built in."""
import hashlib,hmac,secrets,socket,struct
COOKIE=0x2112A442
def attr(kind,value):return struct.pack('!HH',kind,len(value))+value+b'\0'*((-len(value))%4)
def packet(kind,attrs=b'',key=None):
    transaction=secrets.token_bytes(12);header=struct.pack('!HHI',kind,len(attrs)+(24 if key else 0),COOKIE)+transaction
    return header+attrs+(attr(8,hmac.digest(key,header+attrs,'sha1')) if key else b'')
def parse(data):
    kind,length,cookie=struct.unpack('!HHI',data[:8]);assert cookie==COOKIE;fields={};offset=20
    while offset<20+length:
        tag,n=struct.unpack('!HH',data[offset:offset+4]);offset+=4;fields[tag]=data[offset:offset+n];offset+=(n+3)//4*4
    return kind,fields
def error(fields):
    data=fields.get(9,b'\0'*4);return (data[2]&7)*100+data[3]
class Client:
    def __init__(self,port,transport='udp'):
        self.transport=transport
        if transport=='udp':self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.sock.connect(('127.0.0.1',port))
        else:self.sock=socket.create_connection(('127.0.0.1',port),timeout=4)
        self.sock.settimeout(4);self.key=None;self.identity=b''
    def close(self):self.sock.close()
    def exchange(self,kind,attrs=b'',signed=False):
        self.sock.sendall(packet(kind,attrs,self.key if signed else None))
        if self.transport=='udp':return parse(self.sock.recv(65535))
        def exact(n):
            result=b''
            while len(result)<n:
                chunk=self.sock.recv(n-len(result))
                if not chunk:raise RuntimeError('TURN stream closed')
                result+=chunk
            return result
        head=exact(20);return parse(head+exact(struct.unpack('!H',head[2:4])[0]))
    def allocate(self,username,password):
        _,fields=self.exchange(3,attr(0x19,b'\x11\0\0\0'));assert error(fields)==401
        realm,nonce=fields[0x14],fields[0x15];self.key=hashlib.md5(username.encode()+b':'+realm+b':'+password.encode()).digest()
        self.identity=attr(6,username.encode())+attr(0x14,realm)+attr(0x15,nonce)
        return self.exchange(3,self.identity+attr(0x19,b'\x11\0\0\0'),True)
    def permission(self,ip):
        value=struct.pack('!BBH',0,1,3478^(COOKIE>>16))+bytes(a^b for a,b in zip(socket.inet_aton(ip),struct.pack('!I',COOKIE)))
        return self.exchange(8,self.identity+attr(0x12,value),True)
    def release(self):return self.exchange(4,self.identity+attr(0x0d,struct.pack('!I',0)),True)
