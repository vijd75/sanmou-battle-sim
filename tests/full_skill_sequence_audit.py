from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sanmou_sim.models import Battle, DamageKind, General, Modifier, StatusEffect, Team  # noqa: E402
from sanmou_sim.simulator import BattleSimulator  # noqa: E402
from sanmou_sim.skills import _effect_matches_event, _skill_book  # noqa: E402
from audit_skill_effects import EVENTS  # noqa: E402


def run_case(skill, effects: tuple[dict, ...], event: str) -> None:
    owner = General("审计发动者", 100_000, 300, 300, 300, 300, [])
    allies = [General(f"审计友军{i}", 100_000, 250, 250, 250, 250, []) for i in range(2)]
    enemies = [General(f"审计敌军{i}", 100_000, 240, 240, 240, 240, []) for i in range(3)]
    for enemy in enemies:
        enemy.modifiers.append(Modifier("审计属性降低", "force", -10))
        enemy.statuses.append(StatusEffect("畏惧", 2))
    simulator = BattleSimulator(Battle(Team("我方", [owner, *allies]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 3
    context = {
        "actor": owner,
        "attacker": owner,
        "target": enemies[0],
        "damage": 1000,
        "kind": DamageKind.WEAPON,
        "source": skill.name,
    }
    skill._cast_generic(simulator, owner, effects=effects, event=event, context=context)


def main() -> None:
    records = json.loads((ROOT / "data" / "skills.json").read_text(encoding="utf-8"))["skills"]
    book = _skill_book()
    failures: list[str] = []
    cases = 0
    for record in records:
        skill = book[record["name"]]
        named_events = {
            f"named:{effect[key]}"
            for effect in skill.data_effects
            for key in ("effect_name", "trigger_name")
            if effect.get(key)
        }
        for event in (*EVENTS, *sorted(named_events)):
            effects = tuple(effect for effect in skill.data_effects if _effect_matches_event(effect, event, skill.timing))
            if not effects:
                continue
            cases += 1
            try:
                run_case(skill, effects, event)
            except Exception as error:  # noqa: BLE001 - report every case, not only the first.
                failures.append(f"{skill.name} ({event}): {type(error).__name__}: {error}")
    print(f"full skill sequence audit: {len(records)} skills, {cases} event cases, {len(failures)} failures")
    for failure in failures:
        print(failure)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
