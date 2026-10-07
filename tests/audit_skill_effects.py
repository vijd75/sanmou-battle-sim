from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sanmou_sim.models import Battle, General, Modifier, SkillTiming, StatusEffect, Team  # noqa: E402
from sanmou_sim.simulator import BattleSimulator  # noqa: E402
from sanmou_sim.skills import _effect_matches_event, _skill_book  # noqa: E402


EVENTS = (
    "setup",
    "cast",
    "round_start",
    "action_start",
    "action_end",
    "round_end",
    "before_basic_attack",
    "after_basic_attack",
    "before_active_cast",
    "after_active_cast",
    "after_pursuit_cast",
    "active_cast_failed",
    "before_damage_dealt",
    "before_damage_taken",
    "after_damage_dealt",
    "after_damage_taken",
    "after_critical",
    "after_evasion",
    "after_state_applied",
    "state_gained",
    "after_resist_consumed",
    "after_resist_gained",
    "after_heal",
    "after_damage_trigger",
    "after_battle_damage",
)

TIMINGS = {
    "被动": SkillTiming.PASSIVE,
    "指挥": SkillTiming.COMMAND,
    "主动": SkillTiming.ACTIVE,
    "追击": SkillTiming.PURSUIT,
}


def audit_event_mapping() -> tuple[int, list[str]]:
    raw = json.loads((ROOT / "data" / "skills.json").read_text(encoding="utf-8"))
    missing: list[str] = []
    count = 0
    for item in raw["skills"]:
        timing = TIMINGS[item["type"]]
        dynamic_events = list(EVENTS)
        for effect in item.get("effects", []):
            for key in ("effect_name", "trigger_name"):
                if effect.get(key):
                    dynamic_events.append(f"named:{effect[key]}")
        for effect in item.get("effects", []):
            count += 1
            if not any(_effect_matches_event(effect, event, timing) for event in dynamic_events):
                missing.append(f"{item['name']} / {effect.get('kind', '<empty>')}")
    return count, missing


def audit_direct_execution() -> tuple[int, list[str]]:
    failures: list[str] = []
    count = 0
    for skill in _skill_book().values():
        for index, effect in enumerate(skill.data_effects):
            count += 1
            actor = General("审计武将", 100_000, 300, 300, 300, 300, [])
            ally = General("审计友军", 80_000, 250, 250, 250, 250, [], max_troops=100_000, wounded_troops=20_000)
            enemy = General("审计敌军", 100_000, 240, 240, 240, 240, [])
            enemy.modifiers.append(Modifier("审计属性降低", "force", -10))
            for state in ("混乱", "妖术", "畏惧", "流血", "焚烧", "中毒", "抵御"):
                enemy.statuses.append(StatusEffect(state, remaining_rounds=2, stacks=1, max_stacks=5))
            simulator = BattleSimulator(Battle(Team("我方", [actor, ally]), Team("敌方", [enemy]), max_rounds=1), seed=1)
            simulator.round_no = 3
            context = {
                "actor": actor,
                "attacker": enemy,
                "target": enemy,
                "damage": 1000,
                "healing": 500,
                "kind": "weapon",
                "source": "流血",
                "actor_basic_count": 12,
                "team_basic_count": 12,
                "named_count": 4,
            }
            try:
                skill._cast_generic(simulator, actor, effects=(effect,), event="audit", context=context)
            except Exception as error:  # noqa: BLE001 - audit must report every data failure.
                failures.append(f"{skill.name}[{index}] {effect.get('kind')}: {error}")
    return count, failures


if __name__ == "__main__":
    mapped_count, missing = audit_event_mapping()
    executed_count, failures = audit_direct_execution()
    if missing or failures:
        print(f"mapping: {mapped_count - len(missing)}/{mapped_count}")
        print(f"execution: {executed_count - len(failures)}/{executed_count}")
        for message in missing + failures:
            print(message)
        raise SystemExit(1)
    print(f"skill audit ok: mapped {mapped_count}/{mapped_count}, executed {executed_count}/{executed_count}")
