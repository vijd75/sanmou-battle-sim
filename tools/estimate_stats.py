from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


STAT_KEYS = ("force", "intellect", "command", "initiative")


def free_points_between(current_level: int, target_level: int) -> int:
    if target_level < current_level:
        return 0
    return sum(10 for level in (10, 20, 30, 40, 50) if current_level < level <= target_level)


def estimate_stat(current: float, growth: float, current_level: int, target_level: int, allocated: int) -> float:
    return current + growth * (target_level - current_level) + allocated


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Estimate Sanmou general stats at a target level.")
    parser.add_argument("--data", type=Path, default=Path("data/generals.json"))
    parser.add_argument("--level", type=int, default=50)
    parser.add_argument(
        "--allocate",
        nargs="*",
        default=[],
        metavar="GENERAL:STAT:POINTS",
        help="Optional free point allocation, e.g. 刘备:intellect:50",
    )
    args = parser.parse_args()

    allocations: dict[tuple[str, str], int] = {}
    for item in args.allocate:
        name, stat, points = item.split(":")
        allocations[(name, stat)] = int(points)

    catalog = json.loads(args.data.read_text(encoding="utf-8"))
    for general in catalog["generals"]:
        current_level = general.get("current_level", catalog["metadata"]["current_level"])
        free_points = free_points_between(current_level, args.level)
        print(f"{general['name']} Lv{args.level}，可分配属性点: {free_points}")
        for stat in STAT_KEYS:
            entry = general["stats"][stat]
            allocated = allocations.get((general["name"], stat), 0)
            value = estimate_stat(entry["current"], entry["growth"], current_level, args.level, allocated)
            print(f"  {stat}: {value:.2f}")
        print()


if __name__ == "__main__":
    main()
