# 三国谋定天下对战模拟器

这是一个三谋对战模拟器骨架，重点是把对战流程、武将数据、战法效果拆开，方便后续逐步校准到真实游戏。

当前实现参考的公开机制：

- 每场战斗最多 8 回合，未分胜负判定为平局。
- 每回合重新按先攻生成行动顺序；同队内部先攻高者在前，敌我队列逐个比拼，先攻差超过 70 时高先攻必定优先，差距不超过 70 时按先攻权重随机。
- 布阵阶段结算被动和指挥；指挥按武将先攻排序施加，携带者阵亡后移除其指挥效果。
- 回合内按震慑判定、行动触发被动、主动战法、普攻、反击、追击、回合末异常伤害和状态扣时建模。
- 控制状态覆盖震慑、技穷、缴械、混乱、嘲讽、虚弱、断粮；特殊状态覆盖抵御、必中、规避、焚烧、中毒等。
- 兵刃/谋略伤害使用公开公式基底；会心/奇谋为 1.5 倍；逃兵和传递伤害作为独立伤害类型。
- 规避、易伤、受到伤害降低按边际递减公式叠加：`1 - product(1 - rate)`。
- 战斗内伤害按 20% 死兵、80% 伤兵记录；`BattleSimulator.run_campaign()` 可用于连续平局连战。

公开资料入口：

- Bilibili 专栏《三国：谋定天下》战斗机制长文：https://www.bilibili.com/opus/1164737380549132305
- 小米游戏中心《三谋萌新大讲堂（三）：战斗机制解析》
- TapTap《战法系统介绍【三国：谋定天下】》

## 运行

前端配置器：

```powershell
python web\server.py
```

然后打开：

```text
http://localhost:8000/web/index.html
```

配置器支持双方各 3 名武将、自带战法锁定、每名武将额外携带 2 个战法；每个携带战法槽都可直接按战法名检索，下拉候选按指挥、被动、追击、主动分组。队伍可选择一字阵、箕形阵、雁形阵、方圆阵、锥形阵、鱼鳞阵、钩形阵、偃月阵，阵位、受击率和阵型加成会写入导出的 JSON。
点击“开始对战”会调用本地模拟器接口，并在页面下方生成游戏式战后战报：对比双方阵型、剩余兵力和战损，按武将展示每个战法及普通攻击的发动次数、伤害、治疗；逐回合明细可按需展开。

Python 版：

```powershell
$env:PYTHONIOENCODING="utf-8"
python -m sanmou_sim examples/sample_battle.json --seed 7
python -m sanmou_sim examples/sample_battle.json --seed 7 --campaign --max-battles 8
```

C++ 版：

```powershell
cmake -S . -B build
cmake --build build --config Release
.\build\Release\sanmou_sim_cpp.exe examples\sample_battle.json --seed 7
.\build\Release\sanmou_sim_cpp.exe examples\sample_battle.json --seed 7 --campaign --max-battles 8
```

如果你的 CMake 生成器是单配置生成器，可执行文件可能在：

```powershell
.\build\sanmou_sim_cpp.exe examples\sample_battle.json --seed 7
```

如果没有安装 CMake，也可以用编译器直接编：

```powershell
g++ -std=c++17 -O2 cpp\main.cpp cpp\json.cpp cpp\simulator.cpp -Icpp -o sanmou_sim_cpp.exe
.\sanmou_sim_cpp.exe examples\sample_battle.json --seed 7
```

Windows 上推荐安装 Visual Studio Build Tools 或 MinGW-w64，再装 CMake。

如果还没有安装成本地包，也可以这样运行：

```powershell
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONPATH="src"
python -m sanmou_sim examples/sample_battle.json --seed 7
```

## 快速校验

```powershell
$env:PYTHONPATH="src"
python -m compileall -q src tests
python tests/smoke_test.py
```

## 配置格式

对战配置放在 JSON 里。每队 3 名武将，每名武将包含基础属性、兵力和战法列表：

```json
{
  "team_a": {
    "name": "桃园队",
    "generals": [
      {
        "name": "刘备",
        "troops": 6200,
        "force": 115,
        "intellect": 156,
        "command": 148,
        "initiative": 128,
        "skills": ["仁德载世", "避其锐气"]
      }
    ]
  }
}
```

## 数据录入

截图录入的数据放在：

- `data/generals.json`：武将当前等级四维、成长、阵营、定位、自带战法。
- `data/skills.json`：战法类型、特性、概率、1 级到 10 级效果区间、截图原文。

当前按你的说明记录等级规则：

```text
目标等级属性 = 当前属性 + 成长 * (目标等级 - 当前等级) + 自由分配点
```

10、20、30、40、50 级各获得 10 点自由属性。从 5 级升到 50 级，一共可分配 50 点。

可以用这个小工具估算 50 级裸属性：

```powershell
python tools\estimate_stats.py --level 50
python tools\estimate_stats.py --level 50 --allocate 刘备:intellect:50
```

## 下一步适合补的东西

- 录入真实武将面板、红度、等级、兵种和缘分。
- 把每个战法改成单独公式和状态，而不是通用模板。
- 增加多次蒙特卡洛模拟，输出胜率、平均战损、关键战法贡献。
- 增加 Web 页面，做配将输入和战报可视化。
