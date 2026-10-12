"""Package an already verified experiment with sources and local Git history."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', default='delivery_full')
    args = parser.parse_args()
    experiment = ROOT / 'experiments' / args.experiment
    if experiment.parent != ROOT / 'experiments':
        raise RuntimeError('Experiment must be a single folder name')
    manifest = json.loads((experiment / 'manifest.json').read_text())
    if manifest['status'] != 'PASS' or manifest['verification_scope'] != 'RTL_AND_NETLIST':
        raise RuntimeError('Full RTL and netlist verification must pass before packaging')
    for name, expected in manifest['artifact_sha256'].items():
        if sha(experiment / name) != expected:
            raise RuntimeError('Changed experiment artifact: ' + name)
    for name, expected in manifest['source_sha256'].items():
        if sha(experiment / 'source' / name) != expected or sha(ROOT / name) != expected:
            raise RuntimeError('Changed verified source: ' + name)
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise RuntimeError('Commit delivery files before packaging')
    output = ROOT.parent / '交付包'
    output.mkdir(exist_ok=True)
    archive = output / 'Attention_v2_电路与验证交付.zip'
    if archive.exists():
        raise RuntimeError('Archive already exists; preserve or rename it before repackaging')
    bundle = output / 'attention-history.bundle'
    subprocess.run(['git', 'bundle', 'create', str(bundle), 'HEAD'], cwd=ROOT, check=True)
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '.'], cwd=ROOT).decode().split('\0')
    files = [ROOT / p for p in tracked if p]
    files += [p for p in experiment.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    hashes = {str(Path('Attention_source') / p.relative_to(ROOT)): sha(p) for p in files}
    hashes['attention-history.bundle'] = sha(bundle)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, str(Path('Attention_source') / p.relative_to(ROOT)))
        z.write(bundle, bundle.name)
        z.writestr('SHA256.json', json.dumps(hashes, ensure_ascii=False, indent=2))
        z.writestr('打开说明.txt', '先解压，再打开 Attention_source/docs/交付说明.txt。\n'
                   '运行入口与依赖见该文件。原始历史命令中的绝对路径属于原电脑；复现请使用相对路径入口。\n'
                   'attention-history.bundle 为 Git 历史备份，可用 git clone attention-history.bundle 恢复。\n')
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('ZIP integrity failure')
        for name, expected in hashes.items():
            if hashlib.sha256(z.read(name)).hexdigest() != expected:
                raise RuntimeError('Packaged file mismatch: ' + name)
    archive.with_suffix('.zip.sha256').write_text(sha(archive) + '  ' + archive.name + '\n')
    print(f'PACKAGE PASS: {len(hashes)} files, {archive.stat().st_size} bytes; {archive}')


if __name__ == '__main__':
    main()
