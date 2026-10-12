"""Fetch portable MSYS2 binaries. No installer, registry, or global PATH change."""
import hashlib, io, json, pathlib, re, tarfile, subprocess
from concurrent.futures import ThreadPoolExecutor
import zstandard
ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / 'tools' / 'msys2'
BASE = 'https://repo.msys2.org/mingw/ucrt64/'
packages=['iverilog-1~13.0-2','gcc-libs-16.2.0-3','libwinpthread-14.0.0.r353.g6df76fa52-2',
          'bzip2-1.0.8-4','readline-8.3.003-1','zlib-1.3.2-2','termcap-1.3.1-7']
def fetch(package):
    name='mingw-w64-ucrt-x86_64-'+package+'-any.pkg.tar.zst'
    print('Fetching', name, flush=True)
    cache=ROOT/'tools'/name
    if package.startswith('iverilog') and (ROOT/'tools/iverilog.pkg.tar.zst').exists() and (ROOT/'tools/iverilog.pkg.tar.zst').stat().st_size==1988347:
        blob=(ROOT/'tools/iverilog.pkg.tar.zst').read_bytes()
    else:
        subprocess.run(['curl.exe','-f','-L','-sS','--retry','2','--connect-timeout','10','--max-time','120',BASE+name,'-o',str(cache)],check=True)
        blob=cache.read_bytes()
    return name,blob
with ThreadPoolExecutor(max_workers=4) as pool:
    downloads=list(pool.map(fetch,packages))
records=[]
for name,blob in downloads:
    records.append(dict(package=name,url=BASE+name,sha256=hashlib.sha256(blob).hexdigest()))
    data = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(blob))
    with tarfile.open(fileobj=data, mode='r|') as archive:
        for member in archive:
            # Extract only regular files inside the portable distribution prefix.
            if member.isfile() and member.name.startswith('ucrt64/') and '..' not in pathlib.PurePosixPath(member.name).parts:
                target = DEST / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
(ROOT/'tools'/'sources.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
print('Portable Icarus ready:', DEST/'ucrt64'/'bin')
