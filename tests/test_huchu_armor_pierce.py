from __future__ import annotations

import math

from sanmou_sim.models import Battle, General, SkillTiming, Team
from sanmou_sim.simulator import BattleSimulator
from sanmou_sim.skills import skills_for


def test_xuchu_naked_blood_battle_uses_live_force_only_for_armor_pierce() -> None:
    xuchu = General("许褚", 10000, 278, 100, 200, 100, ["裸衣血战"])
    ally = General("队友", 10000, 100, 100, 200, 100, [])
    enemy = General("目标", 10000, 100, 100, 200, 100, [])
    simulator = BattleSimulator(
        Battle(Team("我方", [xuchu, ally]), Team("敌方", [enemy])),
        seed=1,
    )
    skill = skills_for(xuchu, SkillTiming.PASSIVE)[0]
    skill.apply_setup(simulator, xuchu)

    # 裸衣血战的自带武力提升仍来自文本；没有额外塞入胜敌益强的16点。
    assert xuchu.stat("force") == 298
    assert xuchu.modifier_total("force") == 20

    for _ in range(3):
        simulator.perform_basic_attack(xuchu, enemy)
    assert math.isclose(xuchu.modifier_total("armor_pierce"), 0.0)

    simulator.perform_basic_attack(xuchu, enemy)
    expected = 0.02 * (1.074605 + 0.00142047 * xuchu.stat("force"))
    assert math.isclose(xuchu.modifier_total("armor_pierce"), expected, rel_tol=1e-9)
    assert math.isclose(ally.modifier_total("armor_pierce"), expected, rel_tol=1e-9)
