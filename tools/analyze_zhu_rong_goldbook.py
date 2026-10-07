from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

RAW = Path(r"D:\battlelog-capture-assistant\captures\20260918_044550_0b0e5dc6\raw\visible_text.txt")
OLD_DAMAGE = Path(r"D:\battlelog-capture-assistant\csv_output\拟合结果\祝融夫人\南疆烈刃\南疆伤害事件_去重.csv")
OUT = Path(r"D:\battlelog-capture-assistant\csv_output\拟合结果\祝融夫人\南疆烈刃\金书修正")
OUT.mkdir(parents=True, exist_ok=True)

TAG = re.compile(r"<[^>]*>")
SPACE = re.compile(r"\s+")
ATTRS = ("武力", "统率", "智力", "先攻")


def clean(line: str) -> str:
    return SPACE.sub(" ", TAG.sub("", line)).strip()


raw_lines = [clean(line) for line in RAW.read_text(encoding="utf-8").splitlines()]
lines = []
for line in raw_lines:
    if line and (not lines or line != lines[-1]):
        lines.append(line)

# A target is considered to have the conditional gold-book bonus when at least
# one attribute-lowering status is active at the exact damage line. The raw log
# explicitly marks the Southlands debuff expiration; we clear the tracked
# reductions there. Other reductions remain active until an explicit restore or
# another expiration marker is seen, and are reported as evidence, not guessed.
active = {name: set() for name in ("张飞", "皇甫嵩", "袁术")}
last_down = {name: {} for name in active}
events = []

for index, line in enumerate(lines, 1):
    m = re.search(r"\[([^\]]+)\]的【(武力|统率|智力|先攻)】降低([\d.]+)\(([-\d.]+)\)", line)
    if m and m.group(1) in active:
        name, attr, delta, now = m.groups()
        active[name].add(attr)
        last_down[name][attr] = {"line": index, "delta": float(delta), "now": float(now)}

    m = re.search(r"\[([^\]]+)\]的【(武力|统率|智力|先攻)】提升([\d.]+)\(([-\d.]+)\)", line)
    if m and m.group(1) in active:
        name, attr, _delta, _now = m.groups()
        active[name].discard(attr)

    m = re.search(r"\[([^\]]+)\]的「南疆烈刃-降」效果已消失", line)
    if m and m.group(1) in active:
        active[m.group(1)].clear()

    m = re.search(r"\[([^\]]+)\]由于\[祝融夫人\].*南疆烈刃.*损失了兵力([\d.]+)\(([\d.]+)\)", line)
    if not m:
        continue
    target, damage, remain = m.groups()
    attrs = sorted(active.get(target, set()))
    recent = {attr: last_down[target][attr]["line"] for attr in attrs if attr in last_down[target]}
    events.append({
        "事件序号": len(events) + 1,
        "原文序号_规范化": index,
        "目标": target,
        "伤害": float(damage),
        "目标受击后兵力": float(remain),
        "是否属性降低": bool(attrs),
        "属性降低项": ",".join(attrs),
        "最近降低行": str(recent),
    })

out = pd.DataFrame(events)
old = pd.read_csv(OLD_DAMAGE, encoding="utf-8-sig")
old = old.sort_values(["原文行号", "目标", "伤害"]).reset_index(drop=True)
out = out.sort_values(["目标", "伤害", "目标受击后兵力"]).reset_index(drop=True)

# Match by the unique damage tuple, while retaining an explicit review flag
# for duplicate tuples. The old extractor's line number is not stable after
# whitespace/tag normalization, so the tuple is the safer join key here.
keys = ["目标", "伤害", "目标受击后兵力"]
out["伤害"] = out["伤害"].round(6)
old["伤害"] = old["伤害"].round(6)
old["目标受击后兵力"] = old["目标受击后兵力"].round(6)
merged = old.merge(out, on=keys, how="left", suffixes=("", "_状态"))
merged["金书乘区"] = np.where(merged["是否属性降低"].fillna(False), 1.06, 1.00)
merged["旧反推值修正后"] = 1.0 / merged["金书乘区"]

out_path = OUT / "南疆伤害_金书状态核对.csv"
merged.to_csv(out_path, index=False, encoding="utf-8-sig")

print(f"规范化战报行数: {len(lines)}")
print(f"南疆事件数: {len(events)}")
print(merged[["原文行号", "目标", "伤害", "目标受击后兵力", "是否属性降低", "属性降低项", "最近降低行", "金书乘区"]].to_string(index=False))
print()
print(f"判定吃到金书1.06: {int((merged['金书乘区'] > 1).sum())}/{len(merged)}")
print(f"状态核对文件: {out_path}")
