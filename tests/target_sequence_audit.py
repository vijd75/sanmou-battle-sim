from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sanmou_sim.skills import _effect_matches_event, _skill_book
from audit_skill_effects import EVENTS


ALIASES = {"目标", "敌军目标", "友军目标", "伤害目标", "当前目标", "属性降低目标"}


def main() -> None:
    skills = _skill_book()
    candidates = 0
    exceptions: list[str] = []
    for skill in skills.values():
        effects = skill.data_effects
        for index, effect in enumerate(effects[:-1]):
            target = str(effect.get("target", ""))
            next_target = str(effects[index + 1].get("target", ""))
            if skill._target_count(target) <= 1:
                continue
            if next_target not in {target, *ALIASES}:
                continue
            if not any(
                _effect_matches_event(effect, event, skill.timing)
                and _effect_matches_event(effects[index + 1], event, skill.timing)
                for event in EVENTS
            ):
                continue
            candidates += 1
            if skill._target_sequence_end(effects, index) <= index + 1:
                exceptions.append(f"{skill.name}[{index}]: {effect.get('kind')} -> {effects[index + 1].get('kind')}")
    print(f"target sequence audit: {len(skills)} skills, {candidates} adjacent multi-target pairs")
    for exception in exceptions:
        print(f"explicit separate selection: {exception}")
    if exceptions:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
