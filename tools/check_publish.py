#!/usr/bin/env python3
"""Check tracked-source boundaries without printing potential secret values."""
import ipaddress
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES={'.pem','.key','.pfx','.p12','.db','.sqlite','.sqlite3','.log','.zip','.tar','.gz','.exe','.dll','.qcow2'}
PATTERNS={
 'private_key':re.compile(r'^-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----',re.M),
 'provider_token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})\b'),
 'personal_windows_path':re.compile(r'[A-Za-z]:[\\/](?:Users|Documents|Downloads)[\\/]',re.I),
 'credential_in_url':re.compile(r'https?://[^\s/@]+:[^\s/@]+@'),
}
def paths():
    p=subprocess.run(['git','ls-files','--cached','-z'],cwd=ROOT,capture_output=True)
    if p.returncode==0 and p.stdout:
        return [ROOT/n.decode() for n in p.stdout.split(b'\0') if n]
    return [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.relative_to(ROOT).parts]
def findings(path):
    relative=path.relative_to(ROOT);name=relative.as_posix();problems=[]
    if any(part in {'secrets','certs','logs','backups','artifacts','__pycache__'} for part in relative.parts):problems.append('runtime_directory')
    if path.name.startswith('.env') and path.name!='.env.example':problems.append('private_environment_file')
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:problems.append('runtime_or_binary_file')
    raw=path.read_bytes()
    if len(raw)>1024*1024 or b'\0' in raw:problems.append('binary_or_oversize');return problems
    text=raw.decode('utf-8-sig')
    for kind,pattern in PATTERNS.items():
        if pattern.search(text):problems.append(kind)
    for match in re.finditer(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])',text):
        try: address=ipaddress.ip_address(match[0])
        except ValueError:continue
        if address.is_global and not address.is_multicast:problems.append('literal_public_ipv4');break
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
