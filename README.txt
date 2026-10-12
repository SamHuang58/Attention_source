Attention 项目：2026 数字组考核 v2 数值规则

本机初学者入口：双击“开始验证.command”；仅查看最近波形用“查看上次波形.command”。
操作说明：docs/开始使用.txt；输入：docs/learning_input.json；模块结构：docs/电路结构.svg。
该入口先完成 RTL 回归、错误注入与重复运行，再生成正常/暂停两次演示和原始 VCD。
Icarus Verilog 负责仿真，Surfer 负责原生波形查看；不需要 HTML 或综合网表。
终端入口：python3 scripts/demo.py；加 --open 可在成功后打开结果和波形。
本机可用 macOS .command；Windows 用户使用终端入口并自行准备仿真及查看工具。

交付版新增：docs/交付说明.txt、docs/设计分析.txt、docs/交付图/。
最终成品中 04_验证证据/delivery_full 保留完整原始证据。01_答辩材料包含 PPT，02_设计报告包含报告。
本工程目录保留可重新运行的源码；Git 历史另存于项目的交付包目录。

本包包含完整 S=8、d=4 Attention 电路、算法参考模型、测试台、单元测试、综合与运行脚本。
本工程子目录不内嵌报告、历史实验、Python 环境或仿真器；报告和既有证据位于最终成品的对应分类中。它不是免安装离线运行包。
先完整解压 ZIP，再运行。Windows 64 位电脑首次准备需要联网。

一、另一台 Windows 电脑的首次准备
1. 安装 Python 3.12（推荐），安装时勾选 Add python.exe to PATH。
2. 在解压目录打开 PowerShell，执行：
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_simulation.ps1
   此步骤创建本项目专用环境、安装综合工具并下载便携 Icarus 仿真器。
   工具下载需要访问 PyPI 和 MSYS2；旧固定版本下载失败时需另行准备
   Icarus Verilog 13 和 Yosys/yowasp-yosys，并加入 PATH。
3. 准备成功后执行以下运行命令。

二、运行（均在解压后的项目根目录执行）
只运行算法，无需仿真器：
   python scripts/launch.py algorithm
自定义输入的 RTL 仿真、综合和网表仿真：
   python scripts/launch.py custom
快速 RTL 验证（不含综合后网表）：
   python scripts/launch.py quick
完整验证（默认三个种子，含网表、算术单元和错误注入）：
   python scripts/launch.py full

双击对应 .cmd 文件也可以运行。准备失败时不要继续把结果当成通过。
Linux/macOS：安装 Python 3.10+、Icarus Verilog 和 Yosys，确保工具在 PATH；
使用 python3 scripts/launch.py full。Windows 准备脚本和 .cmd 不适用于这些系统。

三、文件导航
rtl/attention_ip.sv       输入存储、状态机、点积和加权累加的主电路
rtl/exp_lut.sv            指数查找表
rtl/unsigned_divider.sv   多周期无符号除法器
model/golden.py           完整整数算法与浮点参考、输入生成
model/research_validation.py  独立高精度参考与扩展验证
tb/                      电路、除法器、查找表及网表测试台
tests/                   参考模型和验证脚本的单元测试
docs/demo_input.json      可修改的示例输入
scripts/                 运行、工具准备和综合脚本

四、输入与算法
q 是 4 个整数；k 和 v 各是 8 行，每行 4 个整数；范围 -128..127。
Score[j] = sum(q[i]*k[j][i])，没有 1/sqrt(d) 缩放。
distance[j] = max(Score)-Score[j]。
Weight[j] 的整数编码 = floor(16*exp(-distance[j])+0.5)。
权重采用 UQ1.4：1 位整数、4 位二进制小数，总共 5 位；编码 16 表示 1.0。
距离 0、1、2、3 的编码分别为 16、6、2、1；距离 >=4 四舍五入后为 0。
L = sum(Weight)，ACC[i] = sum(Weight[j]*v[j][i])。
L 和 ACC 都保留相同的 4 位小数，相除时比例抵消。
输出 = sign(ACC)*floor((abs(ACC)+floor(L/2))/L)，为 8-bit 有符号整数。
本实现约定：四舍五入到最近整数，恰好半整数时远离零，例如 1.5→2、-1.5→-2。
至少一项 distance=0，故合法输入的 L 编码范围为 16..128，不会除零。
详细约定与位宽依据见 docs/v2_contract.md。

五、电路协议
空闲时 start 拉高一拍，start 当拍不接收输入。
随后依次发送 4 项 Q，再按行优先发送 32 对 K/V。
data_ready 高时按当前装载阶段配合 q_valid 或 kv_valid，允许输入停顿。
输出共四拍 out_valid，done 与最后一项同拍；没有输出反压。
无停顿时 start 到最后输出为 264 拍。

六、结果与边界
custom/algorithm 的结果在 results/，编译结果在 build/。
完整/快速验证写入 experiments/独立实验目录；最新成功实验看 experiments/latest.json。
完整验证必须显示 RESEARCH PASS 且 verification_scope 为 RTL_AND_NETLIST。
只运行 algorithm 不能证明 RTL 正确；quick 也不能声称网表验证通过。
v2 要求自行实现 LUT。本项目按上述量化与舍入约定验证，未声称通过隐藏样例。
4 位小数的量化精度有限；与真实浮点 Softmax 的误差单独记录，不代表 RTL 与整数模型不一致。
综合是通用综合，网表是零延迟功能仿真；不包含 FPGA 上板或实际频率证明。
运行仿真不会重新生成报告和 PPT。已完成的答辩材料位于最终成品的 01 与 02 分类。
Git 保留修改前源码；v2 同步修改 RTL、参考模型、测试和运行元数据。
