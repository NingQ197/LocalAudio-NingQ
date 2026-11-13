#!/usr/bin/env python3
"""Check tracked-source boundaries without printing potential secret values."""
import ipaddress
import hashlib
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES={'.pem','.key','.pfx','.p12','.db','.sqlite','.sqlite3','.log','.zip','.tar','.gz','.exe','.dll','.qcow2'}
# Only this explicitly published creator image may bypass text decoding.
# Both its path and exact bytes are fixed; other binary files remain blocked.
DOCUMENT_IMAGES={'docs/assets/creator-card.jpg':'2f84a9a18079ec03523643f02b1d5ce1d467b00511ce9bb90178e6d2756acb82'}
PATTERNS={
 'private_key':re.compile(r'^-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----',re.M),
 'provider_token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})\b'),
 'personal_windows_path':re.compile(r'[A-Za-z]:[\\/](?:Users|Documents|Downloads)[\\/]',re.I),
 'credential_in_url':re.compile(r'https?://[^\s/@]+:[^\s/@]+@'),
}
def paths():
    # Include new source files as well as tracked files. An already populated
    # index must not hide an accidentally created, untracked secret or key.
    p=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,capture_output=True)
    if p.returncode==0 and p.stdout:
        return sorted({ROOT/n.decode('utf-8') for n in p.stdout.split(b'\0') if n})
    return [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.relative_to(ROOT).parts]
def findings(path):
    relative=path.relative_to(ROOT);name=relative.as_posix();problems=[]
    if any(part in {'secrets','certs','logs','backups','artifacts','__pycache__'} for part in relative.parts):problems.append('runtime_directory')
    if path.name.startswith('.env') and path.name!='.env.example':problems.append('private_environment_file')
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:problems.append('runtime_or_binary_file')
    if not path.is_file():
        return problems+['missing_or_nonregular_source_file']
    if path.is_symlink():
        return problems+['source_symlink']
    raw=path.read_bytes()
    if name in DOCUMENT_IMAGES:
        if hashlib.sha256(raw).hexdigest()!=DOCUMENT_IMAGES[name]:problems.append('unapproved_document_image')
        return problems
    if len(raw)>1024*1024 or b'\0' in raw:problems.append('binary_or_oversize');return problems
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:return problems+['non_utf8_source_file']
    for kind,pattern in PATTERNS.items():
        if pattern.search(text):problems.append(kind)
    for match in re.finditer(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])',text):
        try: address=ipaddress.ip_address(match[0])
        except ValueError:continue
        # The deprecated 6to4 anycast range is a policy deny-list constant,
        # not a deployment endpoint. Keep this exception local to that file.
        if name=='server/denied-peers.conf' and address in ipaddress.ip_network((0xc0586300,24)):continue
        if address.is_global and not address.is_multicast:problems.append('literal_public_ipv4');break
    # Inspect IPv6 literals as well as IPv4. Examples use RFC 3849 addresses;
    # actual deployment endpoints belong in the local .env file.
    for match in re.finditer(r'(?<![\w:])[0-9A-Fa-f:.]+(?:%[A-Za-z0-9_.-]+)?(?![\w:])',text):
        value=match[0]
        if value.count(':')<2:continue
        try:address=ipaddress.ip_address(value)
        except ValueError:continue
        if address.version!=6:continue
        # These are policy deny ranges, never public deployment endpoints.
        special=('64:ff9b::/96','64:ff9b:1::/48','100::/64','100:0:0:1::/64','2001::/23','2001:db8::/32','2002::/16','3ffe::/16','3fff::/20','5f00::/16','fc00::/7','fe80::/9','ff00::/8')
        if name in {'server/denied-peers.conf','tools/check_publish.py'} and any(address in ipaddress.ip_network(n) for n in special):continue
        if address.is_global and not address.is_multicast:problems.append('literal_public_ipv6');break
    return sorted(set(problems))
def main():
    checked=paths();errors=[]
    for p in checked:
        for kind in findings(p):errors.append((p.relative_to(ROOT).as_posix(),kind))
    if errors:
        for name,kind in errors:print(f'BLOCKED {name}: {kind}')
        raise SystemExit(1)
    print(f'PASS: {len(checked)} source files; no forbidden runtime files or detected secret patterns')
if __name__=='__main__':main()
