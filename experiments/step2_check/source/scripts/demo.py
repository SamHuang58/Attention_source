"""Beginner entry point: real RTL regression, custom demo, and native VCD viewing."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def view(folder):
    manifest = json.loads((folder/'manifest.json').read_text())
    if manifest['status'] != 'PASS' or not manifest.get('demo'):
        raise ValueError('本次运行未通过或没有演示结果，请先查看失败日志。')
    demo = ROOT/manifest['demo']['folder']
    viewer = shutil.which('surfer')
    if not viewer:
        raise RuntimeError('未安装 Surfer；macOS 可运行 brew install surfer。原始 VCD 已保存。')
    with (folder/'viewer.log').open('a') as log:
        subprocess.Popen([viewer, str(demo/'results/attention.vcd'), '-c', str(demo/'signals.sucl')],
                         cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    if sys.platform == 'darwin':
        subprocess.run(['open', '-a', 'TextEdit', str(folder/'summary.txt')], check=False)
    print('已打开原生波形查看器。按操作说明先看输入暂停和四拍输出。')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default=str(ROOT/'docs/learning_input.json'))
    parser.add_argument('--name')
    parser.add_argument('--open', action='store_true', help='open native waveform viewer after success')
    parser.add_argument('--view-latest', action='store_true', help='view the last attempted demo, without rerunning')
    args=parser.parse_args()
    pointer=ROOT/'experiments/latest_demo.json'
    if args.view_latest:
        view(ROOT/json.loads(pointer.read_text())['run'])
        return 0
    name=args.name or datetime.now(timezone.utc).strftime('demo_%Y%m%dT%H%M%S_%fZ')
    if not name.replace('_','').replace('-','').isalnum() or not name.isascii():
        raise ValueError('实验名只能使用英文字母、数字、下划线和短横线。')
    folder=ROOT/'experiments'/name
    if folder.exists():
        raise FileExistsError('该实验名已存在，请换一个名称；旧结果不会覆盖。')
    folder.parent.mkdir(exist_ok=True)
    # Always point at the attempted run, even if it fails; never silently show an older PASS.
    pointer.write_text(json.dumps({'run':str(folder.relative_to(ROOT))})+'\n')
    log_path=folder.parent/(name+'_console.log')
    command=[sys.executable,'-B','scripts/run_research.py','--name',name,'--skip-netlist',
             '--input',str(Path(args.input).resolve())]
    print('正在进行数值、时序、暂停、复位、错误检测及重复运行检查……',flush=True)
    with log_path.open('w') as log:
        rc=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT).returncode
    if not (folder/'manifest.json').exists():
        print(f'运行失败，查看：{log_path}')
        return rc or 1
    m=json.loads((folder/'manifest.json').read_text())
    passed=rc==0 and m['status']=='PASS' and m.get('demo',{}).get('status')=='PASS'
    if passed:
        demo=m['demo']
        lines=['Attention RTL 验证：通过', '',
               f'数值检查：通过（{m["attention_cases"]} 个案例，中间结果及输出逐项一致）',
               '时序、输入接收、暂停和复位：通过',
               f'错误检测：通过（{len(m["mutation_checks"])} 种故意植入的错误全部发现）',
               '重复运行：通过（同一源码、输入、种子，输出/时序记录/覆盖统计一致）',
               f'预期输出：{demo["expected"]}',f'实际输出：{demo["actual"][0]}',
               f'暂停版输出：{demo["actual"][1]}',
               f'周期数：{demo["cycles"]}（正常 / 加入 6 拍暂停）', '',
               '本轮为 RTL 仿真；不包含综合、物理时序或上板。',
               '以上通过结论限于所测案例；量化与真实浮点结果的误差另外记录。',
               '演示计算表：demo/result.txt', '暂停采样图：demo/pause.svg', '输出采样图：demo/output.svg',
               '原始波形：demo/results/attention.vcd', '完整验证记录：manifest.json',
               f'本次目录：{folder}']
    else:
        lines=['Attention RTL 验证：失败 / 未完成', '', m.get('error','请查看日志'),
               f'失败详情：{folder}/failure.txt', f'运行日志：{log_path}',
               '未完成的检查不能当作通过；本次结果没有替换上一次成功实验。']
    (folder/'summary.txt').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))
    if passed and args.open:
        view(folder)
    return 0 if passed else 1


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f'未完成：{error}',file=sys.stderr)
        raise SystemExit(1)
