"""One-command real RTL regression; fails on tools, compile, protocol or numeric errors."""
import argparse, csv, hashlib, importlib.metadata, json, os, pathlib, platform, shutil, subprocess, sys, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'model'))
from golden import generate, SEED, LUT

def command(args, log):
    p=subprocess.run([str(x) for x in args],cwd=ROOT,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (ROOT/'results'/log).write_text(p.stdout,encoding='utf-8')
    print(p.stdout[-1200:] if log=='synthesis.log' else p.stdout.splitlines()[0] if log=='iverilog_version.log' else p.stdout[-4500:],flush=True)
    if p.returncode: raise RuntimeError(f'Exit {p.returncode}: {args}; see results/{log}')
    return p.stdout

def main():
    a=argparse.ArgumentParser();a.add_argument('--random',type=int,default=1000);a.add_argument('--input');a.add_argument('--synth',action='store_true');p=a.parse_args()
    begin=time.time();cases=generate(p.random,p.input)
    bindir=ROOT/'tools/msys2/ucrt64/bin'
    os.environ['PATH']=str(bindir)+os.pathsep+os.environ['PATH']
    iv=shutil.which('iverilog');vv=shutil.which('vvp')
    if not iv or not vv: raise RuntimeError('Icarus missing: run scripts/fetch_iverilog.py or put iverilog/vvp on PATH')
    # Explicit -B is required for the relocatable MSYS2 package on Windows.
    lib=pathlib.Path(iv).resolve().parent.parent/'lib/ivl'
    ivargs=[iv]+(['-B',str(lib)] if lib.exists() else [])
    version=command(ivargs+['-V'],'iverilog_version.log').splitlines()[0]
    command(ivargs+['-g2012','-Wall','-s','tb_divider','-o','build/divider.vvp','rtl/unsigned_divider.sv','tb/tb_divider.sv'],'divider_compile.log')
    divlog=command([vv,'build/divider.vvp'],'divider_simulation.log')
    command(ivargs+['-g2012','-Wall','-s','tb_attention','-o','build/attention.vvp','rtl/exp_lut.sv','rtl/unsigned_divider.sv','rtl/attention_ip.sv','tb/tb_attention.sv'],'compile.log')
    simlog=command([vv,'build/attention.vvp'],'simulation.log')
    assert 'ATTENTION PASS:' in simlog and 'DIVIDER PASS:' in divlog
    rows=list(csv.DictReader((ROOT/'results/rtl_results.csv').open()))
    assert len(rows)==len(cases)
    for c,r in zip(cases,rows):
        assert [int(r[f'o{d}']) for d in range(4)]==c['output_int']
        assert int(r['cycles'])-int(r['stalls'])==264
    summary=dict(status='PASS',cases=len(cases),outputs=len(cases)*4,divider_cases=1024,reset_states=8,
                 base_cycles=264,load_cycles=36,compute_and_output_cycles=228,clock_period_ns=10,
                 min_cycles=min(int(r['cycles']) for r in rows),max_cycles=max(int(r['cycles']) for r in rows),
                 max_abs_error=max(c['max_abs_error'] for c in cases),
                 mean_abs_error=sum(abs(c['output'][d]-c['float_output'][d]) for c in cases for d in range(4))/(4*len(cases)),
                 reference='v2 UQ1.4 LUT; nearest rounding with ties away from zero')
    if p.synth:
        yosys=shutil.which('yosys') or shutil.which('yowasp-yosys') or str(pathlib.Path(sys.executable).parent/'Scripts/yowasp-yosys.exe')
        text=command([yosys,'-Q','-T','-s','scripts/synth.ys'],'synthesis.log')
        assert 'Found and reported 0 problems' in text
        summary['synthesis']='PASS: generic technology-independent synthesis; no board timing claim'
        command(ivargs+['-g2012','-s','tb_netlist','-o','build/netlist.vvp','build/attention_netlist.v','tb/tb_netlist.sv'],'netlist_compile.log')
        netlog=command([vv,'build/netlist.vvp'],'netlist_simulation.log')
        assert 'NETLIST PASS:' in netlog
        summary['netlist_cases']=len(cases)
    (ROOT/'results/summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    files=[x for dirname in ['rtl','tb','model','scripts'] for x in (ROOT/dirname).rglob('*') if x.is_file() and x.suffix in ['.sv','.py','.ps1','.cmd','.ys','.cjs','.html']]
    if p.input: files.append(pathlib.Path(p.input).resolve())
    source=ROOT.parent/'2026数字组考核.pdf'
    if source.exists():files.append(source)
    manifest=dict(seed=SEED,python=platform.python_version(),simulator=version,elapsed_seconds=round(time.time()-begin,3),
                  dependencies={dist.metadata['Name']:dist.version for dist in importlib.metadata.distributions() if dist.metadata['Name'].lower() in ['zstandard','yowasp-yosys','yowasp-runtime','wasmtime']},
                  parameters={'S':8,'d':4,'input_bits':8,'output_bits':8,'output_fractional_bits':0,'weight_fractional_bits':4,'weight_scale':16,'lut':LUT},
                  command=subprocess.list2cmdline(['python','scripts/run.py','--random',str(p.random)]+(['--input',p.input] if p.input else [])+(['--synth'] if p.synth else [])),
                  arguments=vars(p),sha256={str(x.relative_to(ROOT)) if x.is_relative_to(ROOT) else '../'+x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in files})
    manifest['sha256']['build/vectors.txt']=hashlib.sha256((ROOT/'build/vectors.txt').read_bytes()).hexdigest()
    (ROOT/'results/reproduction.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
