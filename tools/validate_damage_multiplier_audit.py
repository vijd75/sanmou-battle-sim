"""Block damage fitting when key damage dealt/taken multipliers are unaudited."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path


FIELDS = (
    ("攻击者通用造成伤害_pct", "证据_攻击者通用造成伤害"),
    ("攻击者造成兵刃伤害_pct", "证据_攻击者造成兵刃伤害"),
    ("攻击者造成谋略伤害_pct", "证据_攻击者造成谋略伤害"),
    ("目标通用受到伤害降低_pct", "证据_目标通用受到伤害"),
    ("目标受到兵刃伤害降低_pct", "证据_目标受到兵刃伤害降低"),
    ("目标受到谋略伤害降低_pct", "证据_目标受到谋略伤害降低"),
)


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = set(reader.fieldnames or [])
            required = {column for pair in FIELDS for column in pair}
            missing = sorted(required - headers)
            if missing:
                return [f"CSV 缺少必需列：{', '.join(missing)}"]

            rows = list(reader)
    except (OSError, csv.Error, UnicodeError) as exc:
        return [f"无法读取 CSV：{exc}"]

    if not rows:
        errors.append("CSV 没有数据行。")

    for row_number, row in enumerate(rows, start=2):
        event_id = (row.get("事件序号") or row.get("原文行号") or str(row_number)).strip()
        for value_column, evidence_column in FIELDS:
            raw_value = (row.get(value_column) or "").strip()
            evidence = (row.get(evidence_column) or "").strip()
            if not raw_value:
                errors.append(f"第 {row_number} 行（事件 {event_id}）：{value_column} 为空。")
            elif raw_value.casefold() in {"未知", "unknown", "na", "n/a", "null", "none"}:
                errors.append(f"第 {row_number} 行（事件 {event_id}）：{value_column} 未知，禁止拟合。")
            else:
                try:
                    number = float(raw_value.removesuffix("%").strip())
                    if not math.isfinite(number):
                        raise ValueError
                except ValueError:
                    errors.append(
                        f"第 {row_number} 行（事件 {event_id}）：{value_column} 不是有限数值：{raw_value!r}。"
                    )
            if not evidence:
                errors.append(f"第 {row_number} 行（事件 {event_id}）：缺少 {evidence_column}。")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="拟合前检查通用/类型专属伤害乘区及其原文证据是否逐事件齐全。"
    )
    parser.add_argument("csv", type=Path, help="逐击核账 CSV")
    args = parser.parse_args()

    errors = validate(args.csv)
    if errors:
        print(f"核账未通过：{len(errors)} 项问题")
        for error in errors:
            print(f"- {error}")
        return 1

    with args.csv.open("r", encoding="utf-8-sig", newline="") as f:
        count = sum(1 for _ in csv.DictReader(f))
    print(f"核账通过：{count} 条事件的6项增伤/承伤字段均有数值和原文证据。")
    print("只有通过此检查的核账表才能送入拟合。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
