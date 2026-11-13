"""Small local-fixture TURN client; no production endpoint is built in."""
import hashlib,hmac,ipaddress,secrets,socket,ssl,struct
COOKIE=0x2112A442

def attr(kind,value):return struct.pack('!HH',kind,len(value))+value+b'\0'*((-len(value))%4)

def packet(kind,attrs=b'',key=None,transaction=None):
    transaction=transaction or secrets.token_bytes(12)
    header=struct.pack('!HHI',kind,len(attrs)+(24 if key else 0),COOKIE)+transaction
    return header+attrs+(attr(8,hmac.digest(key,header+attrs,'sha1')) if key else b'')

def parse(data):
    if len(data)<20:raise ValueError('Truncated STUN header')
    kind,length,cookie=struct.unpack('!HHI',data[:8])
    if cookie!=COOKIE or len(data)!=20+length:raise ValueError('Invalid STUN header')
    fields={};offset=20
    while offset<20+length:
        if offset+4>len(data):raise ValueError('Truncated STUN attribute')
        tag,n=struct.unpack('!HH',data[offset:offset+4]);offset+=4
        if offset+n>len(data):raise ValueError('Truncated STUN attribute body')
        fields[tag]=data[offset:offset+n];offset+=(n+3)//4*4
    return kind,fields

def error(fields):
    data=fields.get(9,b'\0'*4);return (data[2]&7)*100+data[3]

def peer_address(ip,port,transaction=None):
    address=ipaddress.ip_address(ip)
    if address.version==6 and (transaction is None or len(transaction)!=12):raise ValueError('IPv6 XOR address requires the STUN transaction ID')
    mask=struct.pack('!I',COOKIE)+(transaction or b'')
    return struct.pack('!BBH',0,1 if address.version==4 else 2,port^(COOKIE>>16))+bytes(a^b for a,b in zip(address.packed,mask))

def decode_address(data,transaction=None):
    if len(data)<4 or data[1] not in (1,2):raise ValueError('Invalid XOR address family')
    n=4 if data[1]==1 else 16
    if len(data)!=4+n or (n==16 and (transaction is None or len(transaction)!=12)):raise ValueError('Invalid XOR address length or transaction')
    mask=struct.pack('!I',COOKIE)+(transaction or b'')
    address=ipaddress.ip_address(bytes(a^b for a,b in zip(data[4:],mask)))
    return str(address),struct.unpack('!H',data[2:4])[0]^(COOKIE>>16)

class Client:
    def __init__(self,port,transport='udp',trust_file=None,host='127.0.0.1'):
        self.transport=transport
        if transport=='udp':
            self.sock=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_DGRAM)
            self.sock.connect((host,port))
        else:
            self.sock=socket.create_connection((host,port),timeout=4)
            if transport=='tls':self.sock=ssl.create_default_context(cafile=trust_file).wrap_socket(self.sock,server_hostname='relay.test')
        self.sock.settimeout(4);self.key=None;self.identity=b''
    def close(self):self.sock.close()
    def exchange(self,kind,attrs=b'',signed=False,peer=None):
        transaction=secrets.token_bytes(12)
        if peer is not None:attrs+=attr(0x12,peer_address(peer[0],peer[1],transaction))
        self.sock.sendall(packet(kind,attrs,self.key if signed else None,transaction))
        if self.transport=='udp':data=self.sock.recv(65535)
        else:
            def exact(n):
                result=b''
                while len(result)<n:
                    chunk=self.sock.recv(n-len(result))
                    if not chunk:raise RuntimeError('TURN stream closed')
                    result+=chunk
                return result
            head=exact(20);data=head+exact(struct.unpack('!H',head[2:4])[0])
        if data[8:20]!=transaction:raise ValueError('Unexpected STUN transaction')
        self.last_transaction=transaction
        return parse(data)
    def allocate(self,username,password,family=4):
        request=attr(0x19,b'\x11\0\0\0')
        if family is not None:
            if family not in (4,6):raise ValueError('Invalid requested address family')
            request+=attr(0x17,bytes((1 if family==4 else 2,0,0,0)))
        kind,fields=self.exchange(3,request)
        if error(fields)!=401:return kind,fields
        realm,nonce=fields[0x14],fields[0x15];self.key=hashlib.md5(username.encode()+b':'+realm+b':'+password.encode()).digest()
        self.identity=attr(6,username.encode())+attr(0x14,realm)+attr(0x15,nonce)
        result=self.exchange(3,self.identity+request,True)
        if result[0]==0x103:self.relay=decode_address(result[1][0x16],self.last_transaction)
        return result
    def permission(self,ip):return self.exchange(8,self.identity,True,peer=(ip,3478))
    def send_data(self,ip,port,payload):
        transaction=secrets.token_bytes(12)
        self.sock.sendall(packet(0x16,attr(0x12,peer_address(ip,port,transaction))+attr(0x13,payload),transaction=transaction))
    def receive_data(self):
        if self.transport!='udp':raise ValueError('Data indication fixture uses UDP')
        kind,fields=parse(self.sock.recv(65535))
        if kind!=0x17:raise ValueError('Expected a TURN Data indication')
        return fields[0x13]
    def release(self):return self.exchange(4,self.identity+attr(0x0d,struct.pack('!I',0)),True)
