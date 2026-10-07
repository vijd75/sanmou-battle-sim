from pathlib import Path
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

RAW = Path(r"D:\battlelog-capture-assistant\captures\20260918_044550_0b0e5dc6\raw\visible_text.txt")
TAG = re.compile(r"<[^>]*>")

raw_lines = [TAG.sub("", line).strip() for line in RAW.read_text(encoding="utf-8").splitlines()]
lines = []
for line in raw_lines:
    if line and (not lines or line != lines[-1]):
        lines.append(line)

print(f"cleaned lines: {len(lines)}")
for index, line in enumerate(lines, 1):
    is_damage = "南疆烈刃" in line and "损失了兵力" in line
    is_decrease = "降低" in line and any(name in line for name in ("张飞", "皇甫嵩", "袁术"))
    is_expire = "南疆烈刃-降" in line and "消失" in line
    if is_damage or is_decrease or is_expire:
        print(f"{index}: {line}")
