"""Integer contract and an independent stable floating-point Attention reference."""
import argparse, csv, hashlib, json, math, pathlib, random
ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED = 20260910
SCALE = 1 << 4  # v2：权重保留 4 位二进制小数；整数编码 16 表示 1.0。
LUT = [int(math.floor(SCALE * math.exp(-d) + 0.5)) for d in range(4)]
# LUT = [16, 6, 2, 1]；分差 >= 4 时，16*exp(-d) 四舍五入为 0。

def evaluate(q, k, v):
    # 本项目一次处理 1 个 Q 和 8 组 K/V：q 有 4 个数，k/v 各有 8 行、每行 4 个数。
    # k[j] 与 v[j] 属于同一组信息；j 是组号（0～7），i 是一行内的位置（0～3）。
    # User input checks must still run under python -O. bool is not an int8 value.
    if not isinstance(q, list) or len(q) != 4:
        raise ValueError('q must be a list of 4 signed int8 integers')
    for name, matrix in [('k', k), ('v', v)]:
        if not isinstance(matrix, list) or len(matrix) != 8 or any(
                not isinstance(row, list) or len(row) != 4 for row in matrix):
            raise ValueError(f'{name} must have shape [8][4]')
    if any(type(x) is not int or not -128 <= x <= 127 for x in q+sum(k+v, [])):
        raise ValueError('q, k and v must contain integers in [-128, 127], not bool/float')
    # 对每一行 K 做点积：zip(q, row) 把相同位置的两个数配成一对，乘完再求和。
    # 等价于 score[j] = q[0]*k[j][0] + ... + q[3]*k[j][3]，共得到 8 个分数。
    score = [sum(a*b for a,b in zip(q,row)) for row in k]
    m = max(score)  # 最高分；减去它后，指数表只需处理非负的“距最高分的差”。
    # 分数越接近 m，m-x 越小，查出的权重越大；差距达到 4 时权重取 0。
    weight = [LUT[m-x] if m-x < len(LUT) else 0 for x in score]
    total = sum(weight)  # 8 个权重的总和，也就是最终加权平均的分母。
    # 对输出的每个位置 i，把 8 组 V 的该位置乘各自权重后相加。
    # 例如 acc[0] = weight[0]*v[0][0] + ... + weight[7]*v[7][0]。
    acc = [sum(weight[j]*v[j][i] for j in range(8)) for i in range(4)]
    # ACC 和 L 都含 4 位小数，比例抵消。四舍五入为 int8，半整数远离零。
    output = [(1 if x>=0 else -1)*((abs(x)+total//2)//total) for x in acc]
    # 下面两行用真正的浮点 exp 单独算一遍，供检查上面整数近似的误差。
    e = [math.exp(x-m) for x in score]
    fp = [sum(e[j]*v[j][i] for j in range(8))/sum(e) for i in range(4)]
    assert -65024 <= min(score) <= max(score) <= 65536
    assert SCALE <= total <= 8*SCALE
    assert all(-128<=x<=127 for x in output)
    assert all(min(row[i] for row in v)<=output[i]<=max(row[i] for row in v) for i in range(4))
    return dict(q=q,k=k,v=v,scores=score,max_score=m,weights=weight,L=total,acc=acc,
                output_int=output,output=list(output),float_output=fp,
                max_abs_error=max(abs(output[i]-fp[i]) for i in range(4)))

def generate(n=1000, custom=None, *, seed=SEED, output_root=ROOT, extra_inputs=()):
    if type(n) is not int or n < 0:
        raise ValueError('random case count must be a nonnegative integer')
    output_root = pathlib.Path(output_root)
    rng = random.Random(seed)
    values = [[8,0,-4,2],[0,8,4,-2],[2,2,2,2],[-8,4,0,6],
              [7,-3,5,-1],[1,6,-7,3],[-2,-2,8,4],[4,4,-4,-4]]
    inputs = []
    def add(name,q,k,v): inputs.append((name,q,k,v))
    add('demo_near_scores',[1,0,0,0],[[i,0,0,0] for i in range(8)],values)
    add('uniform_zero_query',[0]*4,[[127,-128,3,5]]*8,values)
    add('all_zero',[0]*4,[[0]*4]*8,[[0]*4]*8)
    add('min_negative_value',[-128]*4,[[-128]*4]*8,[[-128]*4]*8)
    add('max_positive_value',[-128]*4,[[-128]*4]*8,[[127]*4]*8)
    add('score_minimum',[-128]*4,[[127]*4]*8,values)
    add('wide_score_distance',[-128]*4,[[-128]*4]+[[127]*4]*7,values)
    add('negative_fraction',[0]*4,[[0]*4]*8,[[-1,-2,-3,-4]]+[[0]*4]*7)
    add('mixed_signs',[127,-128,127,-128],[[127,-128,-128,127]]*8,values)
    add('single_winner',[127]*4,[[127]*4]+[[-128]*4]*7,values)
    for delta in range(1,15):
        add('lut_distance_'+str(delta),[1,0,0,0],[[0]*4]+[[-delta,0,0,0]]*7,[[127]*4]+[[-128]*4]*7)
    # v2 regression: below/at/above half, both signs and int8 endpoints.
    for numerator in [3, 4, 5, 12, 20]:
        add('round_eighths_'+str(numerator), [0]*4, [[0]*4]*8,
            [[numerator, -numerator, 127, -128]]+[[0, 0, 127, -128]]*7)
    add('round_endpoint_halves', [0]*4, [[0]*4]*8,
        [[127, -128, 127, -128]]*4+[[126, -127, 126, -127]]*4)
    # L=17 is odd: 8/17 rounds to 0, 9/17 to 1 (and symmetrically negative).
    add('round_odd_denominator', [1,0,0,0], [[0]*4,[-3,0,0,0]]+[[-4,0,0,0]]*6,
        [[0]*4,[8,9,-8,-9]]+[[127]*4]*6)
    for i in range(n):
        # Equal coverage of full int8, small scores, and deliberate near ties.
        mode=i%3
        lo,hi=(-128,127) if mode==0 else (-3,3)
        q=[rng.randint(lo,hi) for _ in range(4)]
        k=[[rng.randint(lo,hi) for _ in range(4)] for _ in range(8)]
        if mode==2:
            q=[1,0,0,0]
            k=[[rng.randint(-12,12),0,0,0] for _ in range(8)]
        v=[[rng.randint(-128,127) for _ in range(4)] for _ in range(8)]
        add(f'random_{mode}_{i:04}',q,k,v)
    inputs.extend(extra_inputs)
    if custom:
        x=json.loads(pathlib.Path(custom).read_text(encoding='utf-8-sig'))
        if not isinstance(x, dict) or not all(key in x for key in ['q', 'k', 'v']):
            raise ValueError('input JSON must contain q, k and v')
        inputs=[('custom',x['q'],x['k'],x['v'])]
    cases=[dict(name=name,**evaluate(q,k,v)) for name,q,k,v in inputs]
    (output_root/'build').mkdir(parents=True, exist_ok=True)
    (output_root/'results').mkdir(parents=True, exist_ok=True)
    lines=[str(len(cases))]
    for c in cases:
        seq=c['q']+sum(c['k'],[])+sum(c['v'],[])+c['scores']+c['weights']+[c['L']]+c['acc']+c['output_int']
        lines.append(' '.join(map(str,seq)))
    (output_root/'build'/'vectors.txt').write_text('\n'.join(lines)+'\n',encoding='ascii')
    (output_root/'results'/'golden_cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output_root/'results'/'accuracy.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['case','name','dimension','rounded_int8','float','abs_error'])
        for i,c in enumerate(cases):
            for d in range(4): w.writerow([i,c['name'],d,c['output'][d],c['float_output'][d],abs(c['output'][d]-c['float_output'][d])])
    # Reference generation must not rewrite a user's example/custom input.
    print(f'GOLDEN PASS: {len(cases)} cases; LUT={LUT}; max_abs_error={max(c["max_abs_error"] for c in cases):.9f}')
    return cases

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--random',type=int,default=1000);p.add_argument('--input')
    a=p.parse_args();generate(a.random,a.input)
