"""Build a local event-chain audit for damage events in one decoded battle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DAMAGE_EVENTS = {
    "SoldierNumLossNormal",
    "SoldierNumLossByHeroSkill",
    "SoldierNumLossByBuff",
}
ACTION_EVENTS = {
    "NormalAttack",
    "NormalAttackDouble",
    "SkillLaunch",
    "DoTargetSkillTargetBuff",
}
FLAG_EVENTS = {"ResistEffect", "FatalEffect", "NormalAttackDouble"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--stream", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    battle = next(item for item in summary["battles"] if item["stream_id"] == args.stream)
    events = battle.get("events", battle.get("timeline", []))
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    audits = []
    for position, event in enumerate(events):
        if event.get("event_name") not in DAMAGE_EVENTS:
            continue
        args_data = event.get("args", {})
        start = max(0, position - 20)
        context = events[start:position]
        actions = [
            {
                "event_index": item.get("event_index"),
                "event_name": item.get("event_name"),
                "text": item.get("text"),
                "args": item.get("args", {}),
            }
            for item in context
            if item.get("event_name") in ACTION_EVENTS
        ]
        flags = [
            {
                "event_index": item.get("event_index"),
                "event_name": item.get("event_name"),
                "text": item.get("text"),
                "args": item.get("args", {}),
            }
            for item in context
            if item.get("event_name") in FLAG_EVENTS
        ]
        property_changes = [
            {
                "event_index": item.get("event_index"),
                "event_name": item.get("event_name"),
                "text": item.get("text"),
                "args": item.get("args", {}),
                "names": item.get("names", {}),
            }
            for item in context
            if item.get("event_name", "").startswith("HeroPorperty")
            or item.get("event_name", "").startswith("HeroProperty")
        ]
        audits.append(
            {
                "event_index": event.get("event_index"),
                "round": event.get("round"),
                "event_name": event.get("event_name"),
                "text": event.get("text"),
                "damage_args": args_data,
                "damage_raw_ints": event.get("raw_ints", []),
                "damage_names": event.get("names", {}),
                "unresolved_ids": event.get("unresolved_ids", []),
                "preceding_actions": actions[-5:],
                "preceding_flags": flags,
                "preceding_property_changes": property_changes[-12:],
            }
        )

    with (output / "伤害事件链.jsonl").open("w", encoding="utf-8") as handle:
        for row in audits:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    with (output / "伤害事件链.txt").open("w", encoding="utf-8") as handle:
        for row in audits:
            damage = row["damage_args"]
            handle.write(
                f"[事件 {row['event_index']}][回合 {row['round']}] "
                f"{row['event_name']}\n"
            )
            handle.write(f"伤害结果: {row['text']}\n")
            handle.write("原始伤害参数: " + json.dumps(damage, ensure_ascii=False) + "\n")
            if row["preceding_actions"]:
                handle.write("前置动作:\n")
                for item in row["preceding_actions"]:
                    handle.write(
                        f"  - [{item['event_index']}] {item['event_name']}: "
                        f"{item.get('text') or json.dumps(item['args'], ensure_ascii=False)}\n"
                    )
            if row["preceding_flags"]:
                handle.write("前置特殊判定:\n")
                for item in row["preceding_flags"]:
                    handle.write(
                        f"  - [{item['event_index']}] {item['event_name']}: "
                        f"{item.get('text') or json.dumps(item['args'], ensure_ascii=False)}\n"
                    )
            if row["preceding_property_changes"]:
                handle.write("前置属性变化:\n")
                for item in row["preceding_property_changes"]:
                    handle.write(
                        f"  - [{item['event_index']}] {item['text'] or json.dumps(item['args'], ensure_ascii=False)}\n"
                    )
            handle.write("\n")

    print(f"damage_events={len(audits)}")
    print(f"output={output}")


if __name__ == "__main__":
    main()
