"""Small read-only views of observed RTL samples; VCD remains the full waveform."""
import csv
from html import escape
from pathlib import Path

STATES = ['IDLE', 'LOAD_Q', 'LOAD_KV', 'DOT', 'EXP', 'UPDATE', 'NORM_START', 'NORM_WAIT', 'OUTPUT']


def sample_plot(path, rows, title):
    """One observation per rising edge +1ns, not an interpolated full VCD."""
    labels = ['start', 'q_valid', 'kv_valid', 'ready', 'state', 'dim', 'out_valid', 'out_data', 'done']
    left, step, height = 130, 72, 50
    width = max(850, left + step * len(rows) + 30)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="610" viewBox="0 0 {width} 610">',
             '<rect width="100%" height="100%" fill="#f7f9fc"/>',
             '<style>text{font-family:Arial,"PingFang SC",sans-serif;fill:#182b49;font-size:13px}</style>',
             f'<text x="24" y="32" style="font-size:21px">{escape(title)}</text>',
             '<text x="24" y="57">真实 RTL 上升沿后 1ns 的采样图；完整连续波形请打开 attention.vcd。state/dim 为更新后的值。</text>']
    for col, row in enumerate(rows):
        x = left + step * col
        parts += [f'<path d="M{x} 80V560" stroke="#dbe2ea"/>',
                  f'<text x="{x+3}" y="95">拍 {row["cycle"]}</text>']
    for i, label in enumerate(labels):
        y = 125 + i * height
        parts.append(f'<text x="20" y="{y+15}">{label}</text>')
        for col, row in enumerate(rows):
            x = left + col*step
            val = int(row[label])
            if label in ['state', 'dim', 'out_data']:
                text = STATES[val] if label == 'state' else str(val)
                if label == 'out_data' and row['out_valid'] == '0':
                    text = '无效'
                parts += [f'<rect x="{x}" y="{y}" width="{step}" height="30" fill="#e6edf7" stroke="#fff"/>',
                          f'<text x="{x+4}" y="{y+19}" style="font-size:10px">{text}</text>']
            else:
                level = y + (3 if val else 27)
                prev = int(rows[col-1][label]) if col else val
                prev_level = y + (3 if prev else 27)
                parts.append(f'<path d="M{x} {prev_level}V{level}H{x+step}" fill="none" stroke="#087d79" stroke-width="2"/>')
    parts.append('</svg>')
    path.write_text('\n'.join(parts), encoding='utf-8')


def build(work, cases, observations):
    work = Path(work)
    with (work/'results/cycle_trace.csv').open() as stream:
        trace = list(csv.DictReader(stream))
    paused = [r for r in trace if r['case'] == '1']
    idx = next(i for i,r in enumerate(paused) if r['before_state']=='1' and r['q_valid']=='0')
    sample_plot(work/'pause.svg', paused[max(0,idx-2):idx+6], '暂停三拍：q_valid=0 时，dim 保持为 1')
    normal = [r for r in trace if r['case']=='0']
    idx = next(i for i,r in enumerate(normal) if r['out_valid']=='1')
    sample_plot(work/'output.svg', normal[max(0,idx-2):idx+5], '输出四拍：只有 out_valid=1 时数据有效，done 与最后一项同拍')
    signals = ['clk','rst_n','start','q_valid','kv_valid','data_ready','q_in','k_in','v_in',
               'dut.state','dut.token','dut.dim','dut.weight_sum','debug_acc0','out_valid','out_data','done']
    (work/'signals.sucl').write_text('\n'.join('variable_add tb_attention.'+name for name in signals)+'\nzoom_fit\n')
    c=cases[0]
    lines=['Attention RTL 演示结果（不是完整回归摘要）', '',
           f'Q = {c["q"]}', f'预期输出 = {c["output_int"]}',
           f'实际输出（正常）= {[int(observations[0][f"o{d}"]) for d in range(4)]}',
           f'实际输出（暂停）= {[int(observations[1][f"o{d}"]) for d in range(4)]}',
           '正常运行 264 拍；暂停版多 6 拍，共 270 拍；两次输出一致。', '',
           '以下是 Python 参考计算表；RTL 的 Score/Weight/L/ACC 已由测试台逐项核对。',
           'token | K | V | Score | 权重整数编码 | 实际权重',]
    lines += [f'{j} | {c["k"][j]} | {c["v"][j]} | {c["scores"][j]} | {c["weights"][j]} | {c["weights"][j]/16}' for j in range(8)]
    lines += ['',f'L 编码 = {c["L"]}；实际 L = {c["L"]/16}',
              f'ACC 编码 = {c["acc"]}；实际 ACC = {[v/16 for v in c["acc"]]}',
              '最终 ACC/L 四舍五入成 8 位整数；负半整数远离零。', '',
              '先看 pause.svg、output.svg；它们来自本次 RTL 采样，非手工编造。',
              '完整波形：results/attention.vcd；Surfer 信号配置：signals.sucl。',
              '原始采样：results/cycle_trace.csv；time_ns 单位为 ns，VCD 时间刻度为 ps。',
              '输入：input.json；机器输出：results/rtl_results.csv。',
              '本演示只覆盖此输入的正常/暂停运行。复位、随机、错误注入、重跑一致性见上级 manifest.json。']
    (work/'result.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
