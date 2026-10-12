"""Isolated, fail-closed RTL experiments. Only the Python standard library is needed.

Each run snapshots sources, records exact commands/seeds/tool versions, and writes
its own vectors, observations, logs and final manifest. Never rebuilds documents.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Experiment:
    def __init__(self, args):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        name = args.name or f'run_{stamp}'
        require(re.fullmatch(r'[A-Za-z0-9_-]+', name), '--name must contain ASCII letters, digits, _ or -')
        self.folder = ROOT / 'experiments' / name
        self.folder.mkdir(parents=True, exist_ok=False)
        self.build = self.folder / 'build'
        self.build.mkdir()
        self.logs = self.folder / 'logs'
        self.logs.mkdir()
        self.source = self.folder / 'source'
        self.env = os.environ.copy()
        self.env['PATH'] = str(ROOT / 'tools/msys2/ucrt64/bin') + os.pathsep + self.env.get('PATH', '')
        self.env['PYTHONIOENCODING'] = 'utf-8'
        self.args = args
        self.commands = []
        self.started = time.monotonic()
        self.manifest = {
            'schema_version': 1, 'status': 'RUNNING', 'started_utc': stamp,
            'parameters': vars(args), 'python': sys.version, 'platform': sys.platform,
            'scope': 'S=8,d=4; v2 UQ1.4 exp LUT, signed int8 output, nearest ties away from zero; zero-delay functional simulation',
            'commands': self.commands, 'source_sha256': {}, 'seed_runs': [],
        }
        try:
            self.manifest['git_commit'] = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
            self.manifest['git_dirty'] = bool(subprocess.check_output(
                ['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
        except (OSError, subprocess.CalledProcessError):
            self.manifest['git_commit'] = None
        self.checkpoint()

    def relative(self, path):
        return Path(path).relative_to(ROOT).as_posix()

    def checkpoint(self):
        self.manifest['elapsed_seconds'] = round(time.monotonic() - self.started, 3)
        write_json(self.folder / 'manifest.json', self.manifest)

    def snapshot(self):
        for directory in ['rtl', 'tb', 'model', 'scripts', 'tests']:
            for source in sorted((ROOT / directory).rglob('*')):
                if not source.is_file() or '__pycache__' in source.parts:
                    continue
                relative = source.relative_to(ROOT)
                dest = self.source / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                self.manifest['source_sha256'][relative.as_posix()] = digest(dest)
        lock = ROOT / 'requirements-simulation.lock.txt'
        if lock.exists():
            shutil.copyfile(lock, self.source / lock.name)
            self.manifest['source_sha256'][lock.name] = digest(lock)
        self.checkpoint()

    def command(self, args, label, *, expected_failure=False):
        log = self.logs / (label + '.log')
        command = [str(item) for item in args]
        record = {'argv': command, 'cwd': str(ROOT), 'log': self.relative(log),
                  'expected_failure': expected_failure, 'status': 'RUNNING'}
        self.commands.append(record)
        self.checkpoint()
        started = time.monotonic()
        print(f'[{label}]', flush=True)
        # Stream directly to a log so interruption/timeout does not lose diagnostics.
        try:
            with log.open('w', encoding='utf-8') as output:
                result = subprocess.run(command, cwd=ROOT, env=self.env, stdout=output,
                                        stderr=subprocess.STDOUT, timeout=self.args.timeout)
            record['exit_code'] = result.returncode
            record['status'] = 'FINISHED'
        except subprocess.TimeoutExpired:
            record['status'] = 'TIMEOUT'
            raise RuntimeError(f'{label} exceeded {self.args.timeout}s; see {log}') from None
        finally:
            record['wall_seconds'] = round(time.monotonic() - started, 3)
            self.checkpoint()
        output = log.read_text(encoding='utf-8', errors='replace')
        if expected_failure:
            require(result.returncode != 0 and 'FATAL:' in output,
                    f'{label}: injected defect escaped detection or failed for a non-assertion reason')
        else:
            require(result.returncode == 0, f'{label} failed (exit {result.returncode}); see {log}\n{output[-1800:]}')
        if output.strip():
            lines = output.strip().splitlines()
            print(next((line for line in reversed(lines) if 'PASS:' in line), lines[-1])[:300], flush=True)
        return output

    def compile(self, name, sources, *, top=None, parameters=()):
        target = self.build / (name + '.vvp')
        self.command(self.ivargs + ['-g2012', '-Wall', '-s', top or name,
                     *parameters, '-o', self.relative(target)] + [self.relative(p) for p in sources],
                     name + '_compile')
        return target

    def simulate(self, target, label, plusargs=(), **kwargs):
        return self.command([self.vvp, self.relative(target), *plusargs], label, **kwargs)

    def setup(self):
        self.snapshot()
        self.iverilog = shutil.which('iverilog', path=self.env['PATH'])
        self.vvp = shutil.which('vvp', path=self.env['PATH'])
        require(self.iverilog and self.vvp, 'Icarus missing; run scripts/fetch_iverilog.py')
        self.ivargs = [self.iverilog]
        lib = Path(self.iverilog).resolve().parent.parent / 'lib/ivl'
        if lib.exists():
            self.ivargs += ['-B', str(lib)]
        self.manifest['simulator'] = self.command(self.ivargs + ['-V'], 'iverilog_version').splitlines()[0]
        self.manifest['simulator_sha256'] = digest(self.iverilog)
        self.manifest['vvp_sha256'] = digest(self.vvp)
        self.rtl = [self.source / 'rtl' / name for name in ['exp_lut.sv', 'unsigned_divider.sv', 'attention_ip.sv']]
        self.tb_attention = self.compile('tb_attention', self.rtl + [self.source / 'tb/tb_attention.sv'])
        self.tb_ports = self.compile('tb_ports', self.rtl + [self.source / 'tb/tb_netlist.sv'], top='tb_netlist')
        # Import exactly the source copy being recorded, not a mutable working tree.
        sys.path.insert(0, str(self.source / 'model'))
        from golden import generate
        from research_validation import independent_lut, make_extra_inputs, audit_cases
        self.generate = generate
        self.independent_lut = independent_lut
        self.make_extra_inputs = make_extra_inputs
        self.audit_cases = audit_cases
        self.command([sys.executable, '-m', 'unittest', 'discover', '-s',
                      str(self.source / 'tests'), '-p', 'test_*.py', '-v'], 'python_tests')
        self.command([sys.executable, '-O', '-m', 'unittest', 'discover', '-s',
                      str(self.source / 'tests'), '-p', 'test_*.py'], 'python_optimized_tests')

    def arithmetic(self):
        lut_reference = self.build / 'independent_lut.txt'
        lut_reference.write_text('\n'.join(map(str, self.independent_lut())) + '\n', encoding='ascii')
        self.lut_tb = self.compile('tb_exp_exhaustive', [self.rtl[0], self.source / 'tb/tb_exp_exhaustive.sv'])
        lut_log = self.simulate(self.lut_tb, 'lut_all_addresses', ['+EXPECTED=' + self.relative(lut_reference)])
        require('LUT PASS: all 524288' in lut_log, 'LUT test did not complete')
        arithmetic = {'lut_addresses': 524288, 'divider_widths': {}}
        for width in [1, 2, 4, 8, 16, 36]:
            compiled = self.compile(f'divider_w{width}', [self.rtl[1], self.source / 'tb/tb_divider_exhaustive.sv'],
                                    top='tb_divider_exhaustive', parameters=[f'-Ptb_divider_exhaustive.W={width}'])
            output = self.simulate(compiled, f'divider_w{width}')
            match = re.search(r'DIVIDER EXHAUSTIVE PASS: W=(\d+) cases=(\d+) reset_positions=(\d+)', output)
            require(match and int(match[1]) == width, 'divider test did not complete')
            arithmetic['divider_widths'][str(width)] = {'cases': int(match[2]), 'reset_positions': int(match[3]),
                                                      'all_operand_pairs': width <= 8}
        self.manifest['arithmetic'] = arithmetic
        self.checkpoint()

    def synthesize(self):
        local_yosys = ROOT / 'tools/research-env/Scripts/yowasp-yosys.exe'
        yosys = str(local_yosys) if local_yosys.exists() else (
            shutil.which('yosys', path=self.env['PATH']) or shutil.which('yowasp-yosys', path=self.env['PATH']))
        fallback = Path(sys.executable).parent / 'Scripts/yowasp-yosys.exe'
        if not yosys and fallback.exists():
            yosys = str(fallback)
        require(yosys, 'Yosys/yowasp-yosys is required for the complete experiment')
        self.manifest['synthesis_tool'] = self.command([yosys, '-V'], 'yosys_version').strip()
        self.manifest['synthesis_tool_launcher_sha256'] = digest(yosys)
        if Path(yosys) == local_yosys:
            self.manifest['synthesis_dependencies'] = self.command(
                [str(local_yosys.parent / 'python.exe'), '-m', 'pip', 'freeze'], 'synthesis_environment').splitlines()
            wasm = ROOT / 'tools/research-env/Lib/site-packages/yowasp_yosys/yosys.wasm'
            if wasm.exists():
                self.manifest['synthesis_wasm_sha256'] = digest(wasm)
        script = (self.source / 'scripts/synth.ys').read_text(encoding='utf-8')
        for name in ['exp_lut.sv', 'unsigned_divider.sv', 'attention_ip.sv']:
            script = script.replace('rtl/' + name, self.relative(self.source / 'rtl' / name))
        synth_results = self.folder / 'synthesis'
        synth_results.mkdir()
        script = script.replace('results/', self.relative(synth_results) + '/')
        script = script.replace('build/', self.relative(self.build) + '/')
        script_path = self.build / 'synth.ys'
        script_path.write_text(script, encoding='utf-8')
        output = self.command([yosys, '-Q', '-T', '-s', self.relative(script_path)], 'synthesis')
        require(output.count('Found and reported 0 problems') >= 2, 'synthesis structural checks did not complete')
        stats = json.loads((synth_results / 'synthesis_stats.json').read_text())['design']
        self.manifest['synthesis'] = {
            'status': 'PASS', 'generic_cells': stats['num_cells'],
            'register_bits': sum(n for kind, n in stats['num_cells_by_type'].items() if 'DFF' in kind),
            'qualification': 'Generic synthesis, not device LUT usage, physical timing or board measurement',
        }
        self.tb_netlist = self.compile('tb_gate_netlist', [self.build / 'attention_netlist.v',
                                                        self.source / 'tb/tb_netlist.sv'], top='tb_netlist')

    def verify_rows(self, cases, rows, label):
        require(len(rows) == len(cases), f'{label}: missing/extra observations')
        for index, (case, row) in enumerate(zip(cases, rows)):
            require(int(row['case']) == index, f'{label}: duplicate/reordered case {index}')
            require([int(row[f'o{d}']) for d in range(4)] == case['output_int'], f'{label}: output case={index}')
            require(int(row['cycles']) - int(row['stalls']) == 264, f'{label}: latency case={index}')

    def run_seed(self, seed, index):
        work = self.folder / f'seed_{seed}'
        extra, relations = self.make_extra_inputs(seed, groups=self.args.groups)
        cases = self.generate(self.args.random, seed=seed, output_root=work, extra_inputs=extra)
        write_json(work / 'relations.json', relations)
        result_dir = work / 'results'
        common = ['+VECTORS=' + self.relative(work / 'build/vectors.txt'), '+RESULTS=' + self.relative(result_dir),
                  f'+SEED={seed}', f'+WATCHDOG_CYCLES={max(2000000, len(cases) * (320 + 36 * max(self.args.max_stall, self.args.netlist_stall)))}']
        rtl_log = self.simulate(self.tb_attention, f'seed_{seed}_rtl', common + [f'+MAX_STALL={self.args.max_stall}'])
        require(f'ATTENTION PASS: {len(cases)} cases' in rtl_log, 'RTL test did not complete')
        with (result_dir / 'rtl_results.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        self.verify_rows(cases, rows, 'RTL')
        coverage = json.loads((result_dir / 'functional_coverage.json').read_text())
        require(all(n > 0 for n in coverage['state_cycles']), 'unvisited FSM state')
        require(all(n > 0 for n in coverage['distance_bins_0_to_12_and_tail']), 'uncovered LUT distance')
        require(sum(coverage[k] for k in ['positive_outputs', 'negative_outputs', 'zero_outputs']) == 4 * len(cases),
                'functional coverage output count mismatch')
        require(all(coverage[k] > 0 for k in ['positive_outputs', 'negative_outputs', 'zero_outputs', 'busy_start_cycles']),
                'missing sign or busy-start coverage')
        if self.args.max_stall:
            require(coverage['q_stall_cycles'] > 0 and coverage['kv_stall_cycles'] > 0, 'no input stalls exercised')
        # Repeat the same compiled circuit with the same vectors and seed.
        # VCD timestamps/paths are not reproducibility targets; numeric/protocol observations are.
        replay = work / 'replay'
        replay.mkdir()
        replay_args = [arg for arg in common if not arg.startswith('+RESULTS=')]
        replay_log = self.simulate(self.tb_attention, f'seed_{seed}_replay', replay_args +
            ['+RESULTS=' + self.relative(replay), f'+MAX_STALL={self.args.max_stall}', '+NO_WAVE'])
        require(f'ATTENTION PASS: {len(cases)} cases' in replay_log, 'replay did not complete')
        for filename in ['rtl_results.csv', 'cycle_trace.csv', 'functional_coverage.json']:
            require((result_dir / filename).read_bytes() == (replay / filename).read_bytes(),
                    f'reproducibility mismatch: seed={seed} {filename}')
        numeric = self.audit_cases(cases, rows, relations, result_dir)
        write_json(result_dir / 'numerical_audit.json', numeric)
        # Same port-only test on RTL and netlist with identical random handshake schedule.
        port_args = common + [f'+MAX_STALL={self.args.netlist_stall}']
        ports_log = self.simulate(self.tb_ports, f'seed_{seed}_rtl_ports', port_args)
        require(f'NETLIST PASS: {len(cases)} cases' in ports_log, 'RTL port test did not complete')
        shutil.copyfile(result_dir / 'netlist_results.csv', result_dir / 'rtl_port_results.csv')
        with (result_dir / 'rtl_port_results.csv').open() as stream:
            self.verify_rows(cases, list(csv.DictReader(stream)), 'RTL ports')
        netlist_count = 0
        if not self.args.skip_netlist:
            gate_log = self.simulate(self.tb_netlist, f'seed_{seed}_netlist', port_args)
            require(f'NETLIST PASS: {len(cases)} cases' in gate_log, 'netlist test did not complete')
            require((result_dir / 'netlist_results.csv').read_bytes() == (result_dir / 'rtl_port_results.csv').read_bytes(),
                    'RTL and gate netlist port observations differ')
            with (result_dir / 'netlist_results.csv').open() as stream:
                self.verify_rows(cases, list(csv.DictReader(stream)), 'netlist')
            netlist_count = len(cases)
        summary = {
            'status': 'PASS', 'cases': len(cases), 'outputs': len(cases) * 4, 'base_cycles': 264,
            'min_cycles': min(int(row['cycles']) for row in rows),
            'max_cycles': max(int(row['cycles']) for row in rows),
            'max_abs_error': float(numeric['max_abs_error']), 'mean_abs_error': float(numeric['mean_abs_error']),
            'netlist_cases': netlist_count, 'seed': seed, 'reset_states': 8, 'replay': 'PASS',
            'clock_period_ns': 10, 'reference': 'Independent 80-digit decimal audit; project-defined LUT',
            'synthesis': 'PASS: generic, zero-delay only' if netlist_count else 'NOT RUN',
        }
        write_json(result_dir / 'summary.json', summary)
        seed_record = {'seed': seed, 'folder': self.relative(work), 'summary': summary,
                       'numerical': numeric, 'vectors_sha256': digest(work / 'build/vectors.txt'),
                       'rtl_results_sha256': digest(result_dir / 'rtl_results.csv')}
        self.manifest['seed_runs'].append(seed_record)
        self.checkpoint()
        return work

    def mutation_checks(self, work):
        folder = self.folder / 'mutations'
        folder.mkdir()
        vectors = '+VECTORS=' + self.relative(work / 'build/vectors.txt')
        log_dir = folder / 'observations'
        log_dir.mkdir()
        args = [vectors, '+RESULTS=' + self.relative(log_dir), '+NO_WAVE', '+MAX_STALL=3']
        defects = [
            ('lut_entry', 'exp_lut.sv', "5'd6", "5'd5", 'output case='),
            ('done_alignment', 'attention_ip.sv', 'done <= 1; dim <= 0; state <= IDLE;',
             'done <= 0; dim <= 0; state <= IDLE;', 'done alignment'),
            ('output_sign', 'attention_ip.sv', '-$signed(quotient[7:0])',
             '$signed(quotient[7:0])', 'output case='),
            ('output_rounding', 'attention_ip.sv', 'magnitude + (divisor >> 1)',
             'magnitude', 'output case='),
        ]
        defects.extend([
            ('lost_q', 'attention_ip.sv', 'q_mem[dim] <= q_in;',
             'q_mem[dim] <= 0;', 'Q data capture'),
            ('lost_v', 'attention_ip.sv', 'v_mem[address] <= v_in;',
             'v_mem[address] <= 0;', 'KV data capture'),
            ('ignore_q_valid', 'attention_ip.sv', 'LOAD_Q: if (q_valid)',
             'LOAD_Q: if (1)', 'load counters advanced without handshake'),
            ('ignore_kv_valid', 'attention_ip.sv', 'LOAD_KV: if (kv_valid)',
             'LOAD_KV: if (1)', 'load counters advanced without handshake'),
        ])
        killed = []
        for name, filename, old, new, expected_message in defects:
            source = self.source / 'rtl' / filename
            text = source.read_text()
            require(text.count(old) == 1, f'mutation {name}: target ambiguous')
            mutated = folder / (name + '.sv')
            mutated.write_text(text.replace(old, new), encoding='utf-8')
            sources = [mutated if p.name == filename else p for p in self.rtl]
            target = self.compile('mutant_' + name, sources + [self.source / 'tb/tb_attention.sv'], top='tb_attention')
            output = self.simulate(target, 'mutant_' + name, args, expected_failure=True)
            require(expected_message in output, f'mutation {name}: failure was unrelated to injected defect')
            killed.append({'defect': name, 'status': 'DETECTED', 'expected_diagnostic': expected_message})
        # These two defects were initially missed by the new unit/port tests.
        # Keep them as regression checks for the checkers themselves.
        early = folder / 'early_output.sv'
        original = self.rtl[2].read_text()
        needle = 'if (token == 7) begin token <= 0; state <= DOT; end'
        require(original.count(needle) == 1, 'early-output mutation target ambiguous')
        early.write_text(original.replace(needle,
            'if (token == 7) begin token <= 0; state <= DOT; out_valid <= 1; out_data <= 123; end'), encoding='utf-8')
        target = self.compile('mutant_early_output', self.rtl[:2] + [early, self.source / 'tb/tb_netlist.sv'], top='tb_netlist')
        output = self.simulate(target, 'mutant_early_output', args, expected_failure=True)
        require('final KV handshake' in output, 'unexpected early-output mutation failure')
        killed.append({'defect': 'extra_output_at_final_input', 'status': 'DETECTED'})
        bad_flag = folder / 'bad_divzero_flag.sv'
        original = self.rtl[1].read_text()
        needle = 'if (count == 1) begin quotient <= next_q; busy <= 0; done <= 1; end'
        require(original.count(needle) == 1, 'divide-by-zero mutation target ambiguous')
        bad_flag.write_text(original.replace(needle,
            'if (count == 1) begin quotient <= next_q; busy <= 0; done <= 1; divide_by_zero <= 1; end'), encoding='utf-8')
        target = self.compile('mutant_divzero_flag', [bad_flag, self.source / 'tb/tb_divider_exhaustive.sv'],
                              top='tb_divider_exhaustive', parameters=['-Ptb_divider_exhaustive.W=1'])
        output = self.simulate(target, 'mutant_divzero_flag', expected_failure=True)
        require('false divide-by-zero' in output, 'unexpected divide-by-zero mutation failure')
        killed.append({'defect': 'false_divide_by_zero_on_completion', 'status': 'DETECTED'})
        write_json(folder / 'summary.json', {'status': 'PASS', 'detected': killed,
                   'qualification': 'Ten selected defects; this is not comprehensive mutation coverage'})
        self.manifest['mutation_checks'] = killed

    def demonstration(self, input_path):
        work = self.folder / 'demo'
        work.mkdir()
        saved_input = work / 'input.json'
        shutil.copyfile(input_path, saved_input)
        cases = self.generate(0, custom=saved_input, output_root=work)
        # Same input twice: uninterrupted first, then two explicit three-cycle pauses.
        vectors = work / 'build/vectors.txt'
        lines = vectors.read_text().splitlines()
        vectors.write_text('2\n' + lines[1] + '\n' + lines[1] + '\n', encoding='ascii')
        cases = [dict(cases[0], name='demo_normal'), dict(cases[0], name='demo_paused')]
        results = work / 'results'
        write_json(results / 'golden_cases.json', cases)
        args = ['+VECTORS=' + self.relative(vectors), '+RESULTS=' + self.relative(results),
                '+DEMO', '+TRACE_LIMIT=2', '+SEED=20260922']
        log = self.simulate(self.tb_attention, 'demo_rtl', args)
        require('ATTENTION PASS: 2 cases' in log, 'demo did not complete')
        with (results / 'rtl_results.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        self.verify_rows(cases, rows, 'demo')
        require([int(row['stalls']) for row in rows] == [0, 6], 'demo pause schedule mismatch')
        self.audit_cases(cases, rows, [], results)
        # Use the archived presentation helper; it only reads real simulation observations.
        import importlib.util
        spec = importlib.util.spec_from_file_location('demo_artifacts', self.source / 'scripts/demo_artifacts.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        helper.build(work, cases, rows)
        self.manifest['demo'] = {'status': 'PASS', 'folder': self.relative(work),
                                 'input_sha256': digest(saved_input),
                                 'expected': cases[0]['output_int'],
                                 'actual': [[int(row[f'o{d}']) for d in range(4)] for row in rows],
                                 'cycles': [int(row['cycles']) for row in rows]}
        self.checkpoint()

    def finish(self):
        for relative, sha in self.manifest['source_sha256'].items():
            require(digest(self.source / relative) == sha, f'archived source changed during run: {relative}')
        # Archive every experimental input and observation hash; do not imply old documents were regenerated.
        self.manifest['artifact_sha256'] = {
            p.relative_to(self.folder).as_posix(): digest(p)
            for p in sorted(self.folder.rglob('*'))
            if p.is_file() and 'source' not in p.relative_to(self.folder).parts
            and p.name != 'manifest.json' and p.suffix != '.tmp'
        }
        self.manifest['status'] = 'PASS'
        self.manifest['verification_scope'] = 'RTL_ONLY' if self.args.skip_netlist else 'RTL_AND_NETLIST'
        self.manifest['attention_cases'] = sum(r['summary']['cases'] for r in self.manifest['seed_runs'])
        self.manifest['attention_outputs'] = 4 * self.manifest['attention_cases']
        self.manifest['netlist_cases'] = sum(r['summary']['netlist_cases'] for r in self.manifest['seed_runs'])
        self.manifest['max_abs_error'] = max(r['summary']['max_abs_error'] for r in self.manifest['seed_runs'])
        self.checkpoint()
        # Latest is updated only after every requested stage passes.
        write_json(ROOT / 'experiments/latest.json', {'run': self.relative(self.folder),
                    'manifest_sha256': digest(self.folder / 'manifest.json'),
                    'scope': self.manifest['verification_scope']})
        print(f"RESEARCH PASS: {self.manifest['attention_cases']} cases; {self.manifest['netlist_cases']} netlist cases; {self.folder}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', help='optional custom JSON for a normal and paused demonstration')
    parser.add_argument('--name', help='new experiment directory name; existing runs are never overwritten')
    parser.add_argument('--seeds', nargs='+', type=int, default=[20260910, 20260922, 8675309])
    parser.add_argument('--random', type=int, default=256, help='random cases per seed, plus directed/metamorphic cases')
    parser.add_argument('--groups', type=int, default=32, help='metamorphic groups per seed')
    parser.add_argument('--max-stall', type=int, default=7)
    parser.add_argument('--netlist-stall', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=900, help='wall-clock limit per external command (seconds)')
    parser.add_argument('--skip-netlist', action='store_true', help='explicit RTL-only quick run; recorded as RTL_ONLY')
    parser.add_argument('--skip-mutations', action='store_true')
    args = parser.parse_args()
    parser.error('counts must be nonnegative, stalls <=1000, timeout positive') if (
        args.random < 0 or args.groups < 0 or not 0 <= args.max_stall <= 1000 or
        not 0 <= args.netlist_stall <= 1000 or args.timeout < 1) else None
    if len(set(args.seeds)) != len(args.seeds) or any(not 0 < s < 2**32 for s in args.seeds):
        parser.error('seeds must be unique, nonzero unsigned 32-bit integers')
    return args


def main():
    args = parse_args()
    experiment = Experiment(args)
    print('Experiment:', experiment.folder, flush=True)
    try:
        experiment.setup()
        experiment.arithmetic()
        if not args.skip_netlist:
            experiment.synthesize()
        first_work = None
        for index, seed in enumerate(args.seeds):
            work = experiment.run_seed(seed, index)
            first_work = first_work or work
        if not args.skip_mutations:
            experiment.mutation_checks(first_work)
        if getattr(args, 'input', None):
            experiment.demonstration(Path(args.input).resolve())
        experiment.finish()
    except BaseException as error:
        experiment.manifest['status'] = 'INTERRUPTED' if isinstance(error, KeyboardInterrupt) else 'FAIL'
        experiment.manifest['error'] = str(error)
        (experiment.folder / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        experiment.checkpoint()
        print(f'RESEARCH {experiment.manifest["status"]}: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
