import sys
from random import Random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sanmou_sim.models import Battle, DamageKind, General, Modifier, SkillTiming, StatusEffect, Team
from sanmou_sim.simulator import BattleSimulator
from sanmou_sim.skills import Skill, skills_for
from sanmou_sim.skills import _cleanse_negative_states


def make_simulator() -> tuple[BattleSimulator, General, General, General]:
    owner = General("发动者", 10000, 200, 220, 180, 150, [])
    ally = General("代打友军", 10000, 320, 300, 170, 180, [])
    enemy = General("目标", 10000, 180, 180, 180, 140, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner, ally]), Team("敌方", [enemy])), seed=7)
    simulator.round_no = 1
    return simulator, owner, ally, enemy


def test_damage_reduction_combines_multiplicatively() -> None:
    simulator, _, _, enemy = make_simulator()
    enemy.damage_reduction = 0.20
    enemy.modifiers.append(Modifier("减伤", "damage_taken_reduction", 0.20))
    assert abs(simulator._damage_taken_multiplier(enemy, DamageKind.WEAPON, "active") - 0.64) < 1e-9
    assert simulator._snapshot_general(enemy)["rates"]["受到伤害降低"] == 0.36


def test_vulnerability_is_subtracted_after_reduction_combination() -> None:
    simulator, _, _, enemy = make_simulator()
    enemy.modifiers.extend(
        [
            Modifier("减伤一", "damage_taken_reduction", 0.20),
            Modifier("减伤二", "damage_taken_reduction", 0.20),
            Modifier("畏惧", "damage_taken_increase", 0.10),
        ]
    )
    assert abs(simulator._damage_taken_multiplier(enemy, DamageKind.WEAPON, "active") - 0.74) < 1e-9
    snapshot = simulator._snapshot_general(enemy)
    assert snapshot["rates"]["减伤（未计易伤）"] == 0.36
    assert snapshot["rates"]["受到伤害提升"] == 0.10
    assert snapshot["rates"]["受到伤害降低"] == 0.26

    enemy.modifiers.append(Modifier("减伤三", "damage_taken_reduction", 0.20))
    assert abs(simulator._damage_taken_multiplier(enemy, DamageKind.WEAPON, "active") - 0.612) < 1e-9
    assert simulator._snapshot_general(enemy)["rates"]["受到伤害降低"] == 0.388


def test_reduction_log_uses_multiplicative_total() -> None:
    simulator, owner, ally, _ = make_simulator()
    first = Skill("减伤日志测试一", SkillTiming.ACTIVE, 1.0, "generic", duration=2)
    second = Skill("减伤日志测试二", SkillTiming.ACTIVE, 1.0, "generic", duration=2)
    first._apply_modifier(simulator, owner, [ally], "damage_taken_reduction", 0.20, duration=2, effect={})
    second._apply_modifier(simulator, owner, [ally], "damage_taken_reduction", 0.20, duration=2, effect={})
    assert abs(simulator.damage_taken_reduction_total(ally) - 0.36) < 1e-9
    assert simulator.log[-1] == "代打友军 的【受到伤害降低】提升16.00%（36.00%）"


def test_reduction_log_uses_each_targets_existing_reduction() -> None:
    simulator, owner, ally, _ = make_simulator()
    owner.modifiers.append(Modifier("盾兵加成", "damage_taken_reduction", 0.035))
    ally.modifiers.extend(
        [
            Modifier("盾兵加成", "damage_taken_reduction", 0.035),
            Modifier("其他减伤", "damage_taken_reduction", 0.10),
        ]
    )
    skill = Skill("折冲御侮", SkillTiming.COMMAND, 1.0, "generic")
    before = [simulator.damage_taken_reduction_total(target) for target in (owner, ally)]

    skill._apply_modifier(simulator, owner, [owner, ally], "damage_taken_reduction", 0.296, duration=3, effect={})

    for target, previous, entry in zip((owner, ally), before, simulator.log_entries[-2:]):
        current = simulator.damage_taken_reduction_total(target)
        assert abs(current - (previous + (1.0 - previous) * 0.296)) < 1e-9
        assert entry["text"] == (
            f"{target.name} 的【受到伤害降低】提升{current - previous:.2%}（{current:.2%}）"
        )
        assert entry["states"][target.name][0]["rates"]["减伤（未计易伤）"] == round(current, 4)
        assert abs(simulator._damage_taken_multiplier(target, DamageKind.WEAPON, "active") - (1.0 - current)) < 1e-9
    assert simulator.log[-2] != simulator.log[-1]


def test_snapshot_exposes_contextual_reduction_totals() -> None:
    simulator, _, _, enemy = make_simulator()
    enemy.modifiers.extend(
        [
            Modifier("通用减伤", "damage_taken_reduction", 0.20),
            Modifier("兵刃减伤", "weapon_damage_taken_reduction", 0.20),
        ]
    )
    rates = simulator._snapshot_general(enemy)["rates"]
    assert abs(rates["受到兵刃伤害降低"] - 0.36) < 1e-9
    assert abs(rates["受到谋略伤害降低"] - 0.20) < 1e-9


def test_finite_command_modifier_expires_after_final_round() -> None:
    simulator, owner, ally, _ = make_simulator()
    skill = Skill("限时指挥测试", SkillTiming.COMMAND, 1.0, "generic")
    skill._apply_modifier(
        simulator,
        owner,
        [ally],
        "damage_taken_reduction",
        0.20,
        duration=1,
        effect={"duration_rounds": 1},
    )
    assert ally.modifiers[0].expires_after_turn == 1
    ally.expire_modifiers(1)
    assert ally.modifiers == []


def test_stealing_reduction_uses_post_combination_penalty() -> None:
    simulator, owner, _, enemy = make_simulator()
    enemy.modifiers.extend(
        [
            Modifier("减伤一", "damage_taken_reduction", 0.20),
            Modifier("减伤二", "damage_taken_reduction", 0.20),
        ]
    )
    skill = Skill(
        "夺取减伤测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=(
            {
                "kind": "steal_damage_taken_reduction",
                "target": "敌军单体",
                "value": 0.10,
                "duration_rounds": 1,
            },
        ),
    )
    skill._cast_generic(simulator, owner)
    assert abs(simulator._damage_taken_multiplier(enemy, DamageKind.WEAPON, "active") - 0.74) < 1e-9
    assert abs(simulator._damage_taken_multiplier(owner, DamageKind.WEAPON, "active") - 0.90) < 1e-9
    snapshot = simulator._snapshot_general(enemy)
    assert snapshot["rates"]["减伤（未计易伤）"] == 0.36
    assert snapshot["rates"]["受到伤害提升"] == 0.0
    assert snapshot["rates"]["减伤削减"] == 0.10
    assert snapshot["rates"]["受到伤害降低"] == 0.26


def test_quanyu_jiuxi_uses_calibration_and_grants_lowest_initiative_ally() -> None:
    caopi = General("曹丕", 10000, 100, 300, 200, 160, ["权御九锡"])
    holder = General("九锡持有者", 10000, 100, 120, 200, 60, [])
    ally = General("另一队友", 10000, 100, 140, 200, 180, [])
    enemies = [General(f"敌将{index}", 10000, 100, 200, 200, 100, []) for index in range(3)]
    simulator = BattleSimulator(Battle(Team("我方", [caopi, holder, ally]), Team("敌方", enemies)), seed=5)
    skill = skills_for(caopi, SkillTiming.COMMAND)[0]
    skill.apply_setup(simulator, caopi)

    reduction = 0.1 + 0.000466 * 300 ** 0.892
    assert abs(caopi.modifier_total("damage_taken_reduction") - reduction * 2) < 1e-9
    assert sum(bool(enemy.modifier_total("damage_taken_reduction_penalty")) for enemy in enemies) == 2
    assert holder.has_status("九锡")
    assert not ally.has_status("九锡")

    simulator.round_no = 1
    simulator._trigger_event("action_start", {"actor": holder})
    stolen = (10 + 0.03314 * 300 ** 0.8008) * 0.8
    assert abs(caopi.stat("intellect") - 300) < 1e-9
    assert abs(holder.stat("intellect") - (120 + stolen * 3)) < 1e-9
    assert all(abs(enemy.stat("intellect") - (200 - stolen)) < 1e-9 for enemy in enemies)
    assert sum("九锡持有者 的【智力】提升" in entry for entry in simulator.log) == 3


def test_steal_stat_recalculates_after_each_target() -> None:
    owner = General("夺取者", 10000, 100, 100, 100, 100, [])
    enemies = [General(f"目标{index}", 10000, 100, 100, 100, 100, []) for index in range(2)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    skill = Skill(
        "逐目标夺取",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=({
            "kind": "steal_stat",
            "target": "敌军全体",
            "stat": "智力",
            "calibrated_formula": {"stat": "智力", "intercept": 10, "coefficient": 0.1},
            "stackable": True,
        },),
    )
    skill._cast_generic(simulator, owner)

    assert abs(enemies[0].stat("intellect") - 80) < 1e-9
    assert abs(enemies[1].stat("intellect") - 78) < 1e-9
    assert abs(owner.stat("intellect") - 142) < 1e-9
    assert simulator.log.index("目标0 的【智力】降低20.00（80.00）") < simulator.log.index("目标1 的【智力】降低22.00（78.00）")


def test_each_jiuxi_intellect_reduction_triggers_menghuo_before_next_target() -> None:
    class AlwaysTrigger(Random):
        def random(self) -> float:
            return 0.0

    caopi = General("曹丕", 10000, 100, 300, 200, 160, ["权御九锡"])
    menghuo = General("孟获", 10000, 500, 100, 200, 180, ["雄护南疆"])
    holder = General("九锡持有者", 10000, 100, 120, 200, 60, [])
    enemies = [General(f"敌将{index}", 10000, 100, 200, 200, 100, []) for index in range(3)]
    simulator = BattleSimulator(Battle(Team("我方", [caopi, menghuo, holder]), Team("敌方", enemies)), seed=5)
    simulator.rng = AlwaysTrigger()
    skills_for(caopi, SkillTiming.COMMAND)[0].apply_setup(simulator, caopi)
    simulator.round_no = 1
    simulator._trigger_event("action_start", {"actor": holder})

    reductions = [index for index, entry in enumerate(simulator.log) if "的【智力】降低" in entry]
    triggers = [index for index, entry in enumerate(simulator.log) if entry == "孟获 触发 雄护南疆"]
    assert len(reductions) == len(triggers) == 3
    assert all(reductions[index] < triggers[index] < reductions[index + 1] for index in range(2))
    assert any("孟获 使用 雄护南疆" in entry for entry in simulator.log)
    assert all(enemy.troops < enemy.max_troops for enemy in enemies)
    simulator.on_attribute_reduced(caopi, enemies[0], "非自带战法")
    assert sum(entry == "孟获 触发 雄护南疆" for entry in simulator.log) == 3


def test_daofeng_increases_damage_taken_for_fear_source_not_owner() -> None:
    class AlwaysTrigger(Random):
        def random(self) -> float:
            return 0.0

    owner = General("孟获", 10000, 300, 100, 200, 100, ["蹈锋饮血"])
    attacker = General("祝融夫人", 10000, 300, 100, 200, 120, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", [attacker])), seed=1)
    simulator.rng = AlwaysTrigger()
    simulator.round_no = 1
    skill = skills_for(owner, SkillTiming.PASSIVE)[0]

    context = {"attacker": attacker, "target": owner, "kind": DamageKind.WEAPON, "damage": 100}
    assert skill.trigger(simulator, owner, "after_damage_taken", dict(context))
    assert attacker.has_status("畏惧")
    assert owner.modifier_total("damage_taken_increase") == 0
    assert attacker.modifier_total("damage_taken_increase") == 0.18
    assert skill.trigger(simulator, owner, "after_damage_taken", dict(context))
    assert owner.modifier_total("damage_taken_increase") == 0
    assert attacker.modifier_total("damage_taken_increase") == 0.26


def test_xionghu_gives_yizu_allies_the_extra_weapon_reduction() -> None:
    menghuo = General("孟获", 10000, 300, 100, 200, 100, ["雄护南疆"])
    zhurong = General("祝融夫人", 10000, 300, 100, 200, 120, [])
    ordinary = General("普通队友", 10000, 100, 100, 100, 100, [])
    enemy = General("敌将", 10000, 100, 100, 100, 80, [])
    simulator = BattleSimulator(
        Battle(Team("我方", [menghuo, zhurong, ordinary]), Team("敌方", [enemy])),
        seed=1,
    )

    skill = skills_for(menghuo, SkillTiming.COMMAND)[0]
    assert skill.apply_setup(simulator, menghuo)
    assert menghuo.modifier_total("weapon_damage_taken_reduction") == 0.12
    assert zhurong.modifier_total("weapon_damage_taken_reduction") == 0.12
    assert ordinary.modifier_total("weapon_damage_taken_reduction") == 0.08


def test_xionghu_reactive_damage_stays_on_the_attribute_reduction_target() -> None:
    class AlwaysTrigger(Random):
        def random(self) -> float:
            return 0.0

    source = General("施法者", 10000, 400, 100, 100, 100, ["测试自带"])
    menghuo = General("孟获", 10000, 500, 100, 200, 180, ["雄护南疆"])
    zhurong = General("祝融夫人", 10000, 600, 100, 200, 160, [])
    enemy = General("敌将", 10000, 100, 100, 100, 80, [])
    simulator = BattleSimulator(
        Battle(Team("我方", [source, menghuo, zhurong]), Team("敌方", [enemy])),
        seed=1,
    )
    simulator.rng = AlwaysTrigger()
    simulator.round_no = 1

    simulator.on_attribute_reduced(source, enemy, "测试自带")

    assert enemy.troops < enemy.max_troops
    assert source.troops == source.max_troops
    assert menghuo.troops == menghuo.max_troops
    assert zhurong.troops == zhurong.max_troops
    assert not any("祝融夫人 对 祝融夫人" in entry for entry in simulator.log)


def test_yuxi_holder_gets_bonus_and_deals_damage_at_action_end() -> None:
    owner = General("袁术", 10000, 100, 100, 250, 120, ["僭号天子"])
    holder = General("统率最高的队友", 10000, 100, 100, 500, 100, [])
    enemy = General("敌军", 10000, 100, 100, 100, 80, [])
    simulator = BattleSimulator(
        Battle(Team("我方", [owner, holder]), Team("敌方", [enemy])),
        seed=1,
    )
    simulator._apply_setup_phase()
    simulator.round_no = 4
    simulator._trigger_event("round_start")

    assert holder.has_status("玉玺")
    assert abs(holder.modifier_total("damage_dealt_bonus") - 0.15) < 1e-9
    before = enemy.troops
    simulator._trigger_event("action_end", {"actor": holder})
    assert enemy.troops < before
    assert any("僭号天子" in entry and "兵刃伤害" in entry for entry in simulator.log)


def test_baizhan_uses_sixty_percent_roll_for_one_damage_event() -> None:
    class NeverTrigger(Random):
        def random(self) -> float:
            return 0.99

    owner = General("百战持有者", 10000, 100, 100, 100, 200, ["百战不殆"])
    highest = General("统率最高", 10000, 100, 100, 300, 100, [])
    attacker = General("攻击者", 10000, 200, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner, highest]), Team("敌方", [attacker])), seed=1)
    simulator.round_no = 1
    skill = skills_for(owner, SkillTiming.COMMAND)[0]
    assert skill.apply_setup(simulator, owner)
    assert highest.has_status("百战不殆-统")
    simulator.rng = NeverTrigger()
    assert not skill.trigger(
        simulator,
        owner,
        "after_damage_taken",
        {"attacker": attacker, "target": highest, "kind": DamageKind.WEAPON, "damage": 100},
    )
    assert highest.stat("command") == 300


def test_different_skills_do_not_share_random_target_cache() -> None:
    class CountingRandom(Random):
        def __init__(self) -> None:
            super().__init__(1)
            self.calls = 0

        def random(self) -> float:
            self.calls += 1
            return 0.0

    owner = General("发动者", 10000, 100, 100, 100, 100, [])
    enemies = [General(f"目标{index}", 10000, 100, 100, 100, 100, []) for index in range(2)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.rng = CountingRandom()
    context: dict = {}
    for name in ("降低武力", "降低智力"):
        skill = Skill(
            name, SkillTiming.ACTIVE, 1.0, "generic",
            data_effects=({"kind": "stat_debuff", "target": "敌军随机单体", "stat": "武力", "value": 10},),
        )
        skill._cast_generic(simulator, owner, context=context)
    assert simulator.rng.calls == 2


def test_quanyu_jiuxi_runs_in_full_battle() -> None:
    caopi = General("曹丕", 10000, 100, 300, 200, 160, ["权御九锡"])
    menghuo = General("孟获", 10000, 300, 100, 200, 180, ["雄护南疆"])
    holder = General("九锡持有者", 10000, 100, 120, 200, 60, [])
    enemies = [General(f"敌将{index}", 10000, 100, 200, 200, 100, []) for index in range(3)]
    battle = Battle(Team("我方", [caopi, menghuo, holder]), Team("敌方", enemies), max_rounds=1)
    result = BattleSimulator(battle, seed=5).run()
    assert sum("九锡持有者 的【智力】提升" in entry for entry in result.log) == 3
    assert not any("曹丕 的【智力】提升" in entry for entry in result.log)


def test_multi_target_self_scaling_is_recomputed_for_next_general() -> None:
    owner = General("发动者", 10000, 100, 100, 100, 100, [])
    ally = General("队友", 10000, 100, 100, 100, 100, [])
    enemy = General("敌将", 10000, 100, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner, ally]), Team("敌方", [enemy])), seed=1)
    skill = Skill("自属性逐目标", SkillTiming.COMMAND, 1.0, "generic")
    effect = {
        "kind": "attribute_bonus_from_self",
        "target": "我军全体",
        "attributes": ["武力"],
        "source_attribute_ratio": 0.1,
    }
    skill._cast_special_effect(simulator, owner, effect, "setup", {})
    assert owner.stat("force") == 110
    assert ally.stat("force") == 111
    assert simulator.log[-2:] == [
        "发动者 的【武力】提升10.00（110.00）",
        "队友 的【武力】提升11.00（111.00）",
    ]


def test_damage_bonus_and_type_bonus_share_cap() -> None:
    simulator, owner, _, _ = make_simulator()
    owner.modifiers.extend(
        [
            Modifier("通用", "damage_dealt_bonus", 1.0),
            Modifier("兵刃", "weapon_damage_bonus", 0.5),
        ]
    )
    assert simulator._damage_dealt_multiplier(owner, DamageKind.WEAPON, "active") == 2.0
    snapshot = simulator._snapshot_general(owner)
    assert snapshot["rates"]["造成伤害"] == 1.0
    assert snapshot["rates"]["兵刃通用增伤（实际）"] == 1.0


def test_independent_damage_bonus_multiplies_after_shared_bonus() -> None:
    simulator, owner, _, _ = make_simulator()
    owner.modifiers.extend(
        [
            Modifier("通用", "damage_dealt_bonus", 0.8),
            Modifier("兵刃", "weapon_damage_bonus", 0.7),
            Modifier("主动", "active_damage_bonus", 0.25),
        ]
    )
    assert simulator._damage_dealt_multiplier(owner, DamageKind.WEAPON, "active") == 2.5


def test_weakness_reduces_final_damage_by_seventy_percent() -> None:
    simulator, owner, _, _ = make_simulator()
    owner.modifiers.append(Modifier("通用增伤", "damage_dealt_bonus", 1.0))
    assert simulator._damage_dealt_multiplier(owner, DamageKind.WEAPON, "active") == 2.0
    owner.statuses.append(StatusEffect("虚弱", remaining_rounds=1))
    assert abs(simulator._damage_dealt_multiplier(owner, DamageKind.WEAPON, "active") - 0.60) < 1e-9


def test_base_damage_formulas() -> None:
    simulator, owner, _, enemy = make_simulator()
    owner.force = 351
    owner.intellect = 201
    enemy.command = 121
    enemy.intellect = 101
    assert simulator._raw_damage(owner, enemy, 1.0, DamageKind.WEAPON, "普通攻击") == 316
    assert simulator._raw_damage(owner, enemy, 1.0, DamageKind.STRATEGY, "测试谋略") == 531


def test_faction_bonus_applies_to_all_four_attributes() -> None:
    same = [
        General("魏一", 10000, 200, 200, 200, 200, [], faction="魏"),
        General("魏二", 10000, 200, 200, 200, 200, [], faction="魏"),
        General("魏三", 10000, 200, 200, 200, 200, [], faction="魏"),
    ]
    enemy = General("敌军", 10000, 200, 200, 200, 200, [], faction="蜀")
    simulator = BattleSimulator(Battle(Team("我方", same), Team("敌方", [enemy])), seed=7)
    simulator._apply_faction_bonuses()
    assert all(
        abs(same[0].stat(stat) - 220.0) < 1e-9
        for stat in ("force", "intellect", "command", "initiative")
    )
    assert sum("获得【阵营加成】" in entry for entry in simulator.log) == 3
    assert all(sum(modifier.source_skill == "阵营加成" for modifier in general.modifiers) == 4 for general in same)

    simulator._apply_faction_bonuses()
    assert all(sum(modifier.source_skill == "阵营加成" for modifier in general.modifiers) == 4 for general in same)


def test_two_same_faction_gives_five_percent_and_three_different_gives_none() -> None:
    two_same = [
        General("魏一", 10000, 200, 200, 200, 200, [], faction="魏"),
        General("魏二", 10000, 200, 200, 200, 200, [], faction="魏"),
        General("蜀一", 10000, 200, 200, 200, 200, [], faction="蜀"),
    ]
    all_different = [
        General("魏一", 10000, 200, 200, 200, 200, [], faction="魏"),
        General("蜀一", 10000, 200, 200, 200, 200, [], faction="蜀"),
        General("吴一", 10000, 200, 200, 200, 200, [], faction="吴"),
    ]
    enemy = General("敌军", 10000, 200, 200, 200, 200, [], faction="群")
    two_simulator = BattleSimulator(Battle(Team("我方", two_same), Team("敌方", [enemy])), seed=7)
    two_simulator._apply_faction_bonuses()
    assert two_same[0].stat("force") == 210.0
    assert two_same[2].stat("initiative") == 210.0

    none_simulator = BattleSimulator(Battle(Team("我方", all_different), Team("敌方", [enemy])), seed=7)
    none_simulator._apply_faction_bonuses()
    assert all(general.stat(stat) == 200.0 for general in all_different for stat in ("force", "intellect", "command", "initiative"))


def test_troop_bonus_applies_to_all_team_members_and_refreshes() -> None:
    shield = [
        General("盾一", 10000, 200, 200, 200, 200, [], troop_type="盾兵"),
        General("盾二", 10000, 200, 200, 200, 200, [], troop_type="盾兵"),
        General("盾三", 10000, 200, 200, 200, 200, [], troop_type="盾兵"),
    ]
    enemy = General("敌军", 10000, 200, 200, 200, 200, [], troop_type="弓兵")
    simulator = BattleSimulator(Battle(Team("我方", shield), Team("敌方", [enemy])), seed=7)

    simulator._apply_troop_bonuses()
    assert all(abs(simulator.damage_taken_reduction_total(general) - 0.05) < 1e-9 for general in shield)
    assert all(sum(modifier.source_skill == "兵种加成" for modifier in general.modifiers) == 1 for general in shield)

    simulator._apply_troop_bonuses()
    assert all(sum(modifier.source_skill == "兵种加成" for modifier in general.modifiers) == 1 for general in shield)


def test_two_and_three_member_troop_bonus_values_use_shared_damage_pools() -> None:
    spear_pair = [
        General("枪一", 10000, 200, 200, 200, 200, [], troop_type="枪兵"),
        General("枪二", 10000, 200, 200, 200, 200, [], troop_type="枪兵"),
        General("其他", 10000, 200, 200, 200, 200, [], troop_type="弓兵"),
    ]
    horse_trio = [
        General("骑一", 10000, 200, 200, 200, 200, [], troop_type="骑兵"),
        General("骑二", 10000, 200, 200, 200, 200, [], troop_type="骑兵"),
        General("骑三", 10000, 200, 200, 200, 200, [], troop_type="骑兵"),
    ]
    enemy = General("敌军", 10000, 200, 200, 200, 200, [], troop_type="盾兵")

    pair_simulator = BattleSimulator(Battle(Team("我方", spear_pair), Team("敌方", [enemy])), seed=7)
    pair_simulator._apply_troop_bonuses()
    assert all(
        abs(pair_simulator._damage_dealt_multiplier(general, DamageKind.WEAPON, "active") - 1.021) < 1e-9
        for general in spear_pair
    )
    assert all(abs(pair_simulator.damage_taken_reduction_total(general) - 0.014) < 1e-9 for general in spear_pair)

    trio_simulator = BattleSimulator(Battle(Team("我方", horse_trio), Team("敌方", [enemy])), seed=7)
    trio_simulator._apply_troop_bonuses()
    assert all(
        abs(trio_simulator._damage_dealt_multiplier(general, DamageKind.WEAPON, "active") - 1.02) < 1e-9
        for general in horse_trio
    )
    assert all(abs(trio_simulator.damage_taken_reduction_total(general) - 0.03) < 1e-9 for general in horse_trio)


def test_defeated_general_loses_all_carried_skill_effects_immediately() -> None:
    source = General(
        "阵亡武将",
        100,
        200,
        200,
        200,
        200,
        ["来源战法一", "来源战法二", "来源战法三"],
    )
    ally = General("友军", 10000, 200, 200, 200, 200, [])
    attacker = General("击杀者", 10000, 300, 100, 100, 100, [])
    source_effect = Modifier(
        "来源战法一",
        "force",
        15,
        source_actor=source.name,
        source_skill="来源战法一",
    )
    source.modifiers.append(source_effect)
    ally.modifiers.extend(
        [
            Modifier(
                "来源战法一",
                "damage_taken_reduction",
                0.20,
                source_actor=source.name,
                source_skill="来源战法一",
            ),
            Modifier(
                "来源战法二",
                "force",
                20,
                source_actor=source.name,
                source_skill="来源战法二",
            ),
            Modifier(
                "其他来源",
                "force",
                7,
                source_actor="其他武将",
                source_skill="其他战法",
            ),
        ]
    )
    ally.statuses.append(
        StatusEffect(
            "畏惧",
            remaining_rounds=2,
            source_actor=source.name,
            payload={"source_skill": "来源战法三"},
        )
    )
    simulator = BattleSimulator(Battle(Team("我方", [source, ally]), Team("敌方", [attacker])), seed=7)

    simulator.deal_damage(attacker, source, 10.0, DamageKind.WEAPON, "击杀测试")

    assert source.troops == 0
    assert source.stat("force") == 200.0
    assert ally.stat("force") == 207.0
    assert ally.modifier_total("damage_taken_reduction") == 0.0
    assert not any(status.name == "畏惧" for status in ally.statuses)
    assert any("【阵亡武将】兵力为0，无法再战。" in line for line in simulator.log)
    assert sum("【阵亡武将】兵力为0，无法再战。" in line for line in simulator.log) == 1
    assert any(modifier.source_skill == "其他战法" for modifier in ally.modifiers)

    simulator._on_general_defeated(source)
    assert sum("【阵亡武将】兵力为0，无法再战。" in line for line in simulator.log) == 1


def test_non_stackable_modifier_refreshes() -> None:
    simulator, owner, ally, _ = make_simulator()
    skill = Skill("刷新测试", SkillTiming.ACTIVE, 1.0, "generic", duration=2)
    skill._apply_modifier(simulator, owner, [ally], "damage_dealt_bonus", 0.2, duration=2, effect={})
    simulator.round_no = 2
    skill._apply_modifier(simulator, owner, [ally], "damage_dealt_bonus", 0.2, duration=2, effect={})
    matching = [modifier for modifier in ally.modifiers if modifier.source_skill == skill.name]
    assert len(matching) == 1
    assert matching[0].expires_after_turn == 3
    assert any("持续时间已刷新" in line for line in simulator.log)


def test_explicit_stack_respects_cap() -> None:
    simulator, owner, ally, _ = make_simulator()
    skill = Skill("叠层测试", SkillTiming.ACTIVE, 1.0, "generic", raw_text="可叠加2层")
    effect = {"kind": "stacking_damage_rate_bonus", "max_stacks": 2}
    for _ in range(3):
        skill._apply_modifier(simulator, owner, [ally], "damage_dealt_bonus", 0.1, duration=2, effect=effect)
    matching = [modifier for modifier in ally.modifiers if modifier.source_skill == skill.name]
    assert len(matching) == 2
    assert any("已满2层" in line for line in simulator.log)


def test_delegated_damage_uses_actual_source() -> None:
    simulator, owner, ally, enemy = make_simulator()
    skill = Skill(
        "指点测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=(
            {
                "kind": "weapon_damage",
                "source": "我军武力最高单体",
                "target": "敌军全体",
                "damage_rate_at_level_10": 0.8,
            },
        ),
    )
    skill._cast_generic(simulator, owner)
    assert enemy.troops < enemy.max_troops
    assert any("发动者 发动 指点测试，令 代打友军 对 目标" in line for line in simulator.log)
    assert any(line.endswith(f"（{enemy.troops}）") for line in simulator.log if "指点测试" in line and "造成" in line)
    assert simulator._source_stat(owner, skill.name).damage > 0
    assert simulator._source_stat(ally, skill.name).damage == 0


def test_deserters_settle_immediately() -> None:
    simulator, owner, _, enemy = make_simulator()
    skill = Skill(
        "逃兵测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=({"kind": "apply_state", "state": "逃兵", "target": "敌军全体"},),
    )
    skill._cast_generic(simulator, owner)
    assert enemy.troops == 9700
    assert not enemy.has_status("逃兵")
    assert any("产生 300 逃兵，立即损失 300 兵力（9700）" in line for line in simulator.log)


def test_known_and_pending_deserter_formulas() -> None:
    target = General("目标", 10000, 180, 180, 180, 140, [])

    guan_yu = General("关羽", 10000, 300, 120, 220, 150, ["威震华夏"])
    guan_skill = skills_for(guan_yu, SkillTiming.ACTIVE)[0]
    guan_effect = next(effect for effect in guan_skill.data_effects if effect.get("state") == "逃兵")
    assert guan_skill._deserter_amount(guan_yu, target, guan_effect) == 390

    jiang_wei = General("姜维", 10000, 200, 220, 180, 150, ["九伐中原"])
    jiang_skill = skills_for(jiang_wei, SkillTiming.COMMAND)[0]
    jiang_effect = next(effect for effect in jiang_skill.data_effects if effect.get("state") == "逃兵")
    assert jiang_skill._deserter_amount(jiang_wei, target, jiang_effect) == 377

    for name, skill_name in (("程昱", "勇冠贲育"), ("群孙坚", "诛凶殄逆")):
        actor = General(name, 10000, 300, 300, 200, 150, [skill_name])
        skill = skills_for(actor, SkillTiming.ACTIVE)[0]
        effect = next(item for item in skill.data_effects if item.get("state") == "逃兵")
        assert skill._deserter_amount(actor, target, effect) is None

    simulator = BattleSimulator(Battle(Team("我方", [guan_yu]), Team("敌方", [target])), seed=7)
    pending_skill = Skill(
        "待拟合逃兵测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=(
            {
                "kind": "apply_state",
                "state": "逃兵",
                "target": "敌军单体",
                "implementation_status": "pending_fit",
            },
        ),
    )
    pending_skill._cast_generic(simulator, guan_yu)
    assert target.troops == target.max_troops
    assert any("逃兵公式待实测拟合，本次暂不结算逃兵" in line for line in simulator.log)


def test_structured_skill_does_not_repeat_text_status_fallback() -> None:
    actor = General("张飞", 10000, 300, 100, 200, 180, ["万人之敌"])
    enemies = [
        General("曹操", 10000, 180, 260, 220, 150, []),
        General("典韦", 10000, 280, 80, 230, 140, []),
        General("许褚", 10000, 290, 70, 225, 130, []),
    ]
    simulator = BattleSimulator(Battle(Team("我方", [actor]), Team("敌方", enemies)), seed=7)
    simulator.round_no = 1
    skill = skills_for(actor, SkillTiming.ACTIVE)[0]
    skill._cast_generic(simulator, actor)
    assert sum("获得 畏惧" in line for line in simulator.log) == 3
    assert not any("畏惧」持续时间已刷新" in line for line in simulator.log)
    assert not any("获得 震慑" in line for line in simulator.log)


def test_healing_uses_fitted_intelligence_function_without_troop_factor() -> None:
    healer = General("华佗", 10000, 80, 340, 180, 160, [])
    target = General("伤员", 5000, 180, 100, 180, 120, [], max_troops=10000, wounded_troops=5000)
    enemy = General("敌军", 10000, 180, 180, 180, 120, [])
    simulator = BattleSimulator(Battle(Team("我方", [healer, target]), Team("敌方", [enemy])), seed=7)
    amount = simulator.heal(healer, target, 1.8, "治疗测试")
    assert amount == 778
    healer.troops = 5000
    target.troops = 5000
    amount_at_half_troops = simulator.heal(healer, target, 1.8, "治疗测试")
    assert amount_at_half_troops == 778


def test_forgot_self_help_uses_intellect_and_command_fit() -> None:
    samples = [
        (420.81, 213.93, 0.515, 260),
        (405.81, 213.93, 0.515, 249),
        (436.79, 213.93, 0.515, 273),
        (513.74, 213.93, 0.515, 340),
        (529.71, 213.93, 0.515, 355),
        (162.58, 466.57, 0.53, 223),
        (173.62, 442.37, 0.53, 214),
        (173.62, 467.37, 0.53, 227),
        (80.64, 441.43, 0.50, 179),
    ]
    for intellect, command, rate, expected in samples:
        healer = General("治疗者", 10000, 100, intellect, command, 100, [])
        target = General("伤员", 1, 100, 100, 100, 100, [], max_troops=10000)
        enemy = General("敌军", 10000, 100, 100, 100, 100, [])
        simulator = BattleSimulator(Battle(Team("我方", [healer, target]), Team("敌方", [enemy])), seed=7)
        assert simulator.heal(healer, target, rate, "忘私相助") == expected


def test_starvation_reduces_all_received_healing_by_seventy_percent() -> None:
    healer = General("华佗", 10000, 80, 340, 180, 160, [])
    target = General("伤员", 5000, 180, 100, 180, 120, [], max_troops=10000, wounded_troops=5000)
    enemy = General("敌军", 10000, 180, 180, 180, 120, [])
    simulator = BattleSimulator(Battle(Team("我方", [healer, target]), Team("敌方", [enemy])), seed=7)
    target.statuses.append(StatusEffect("断粮", remaining_rounds=1))
    assert simulator.heal(healer, target, 1.8, "治疗测试") == 233
    target.troops = 5000
    assert simulator.heal_fixed(healer, target, 1000, "固定治疗测试") == 300


def test_named_abnormal_status_values_and_critical_multiplier() -> None:
    simulator, owner, _, enemy = make_simulator()
    skill = Skill(
        "异常状态测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        duration=2,
        data_effects=tuple(
            {"kind": "apply_state", "state": state, "target": "敌军单体", "duration_rounds": 2}
            for state in ("洪水", "火攻", "风暴", "畏惧", "妖术")
        ),
    )
    skill._cast_generic(simulator, owner)
    assert enemy.stat("command") == 160
    assert enemy.stat("intellect") == 165
    assert enemy.stat("initiative") == 110
    assert abs(simulator._damage_taken_multiplier(enemy, DamageKind.WEAPON, "active") - 1.10) < 1e-9
    enemy.critical_chance = 1.0
    assert abs(simulator._critical_multiplier(enemy, DamageKind.WEAPON) - 1.35) < 1e-9
    assert abs(simulator._critical_multiplier(enemy, DamageKind.STRATEGY) - 1.35) < 1e-9
    matching = [modifier for modifier in enemy.modifiers if modifier.source_skill == skill.name]
    assert matching and all(modifier.expires_after_turn == 2 for modifier in matching)


def test_strategy_critical_damage_adds_to_one_hundred_fifty_percent_base() -> None:
    simulator, owner, _, _ = make_simulator()
    owner.critical_chance = 1.0
    assert abs(simulator._critical_multiplier(owner, DamageKind.STRATEGY) - 1.50) < 1e-9
    owner.modifiers.append(Modifier("奇谋增伤", "strategy_critical_damage_bonus", 0.25))
    assert abs(simulator._critical_multiplier(owner, DamageKind.STRATEGY) - 1.75) < 1e-9


def test_confusion_randomizes_active_and_pursuit_hostile_targets() -> None:
    for timing in (SkillTiming.ACTIVE, SkillTiming.PURSUIT):
        hit_ally = False
        for seed in range(40):
            actor = General("混乱者", 10000, 300, 100, 180, 150, [])
            ally = General("友军", 10000, 180, 180, 180, 140, [])
            enemy = General("敌军", 10000, 180, 180, 180, 130, [])
            simulator = BattleSimulator(Battle(Team("我方", [actor, ally]), Team("敌方", [enemy])), seed=seed)
            simulator.round_no = 1
            actor.statuses.append(StatusEffect("混乱", remaining_rounds=1))
            skill = Skill(
                "混乱目标测试",
                timing,
                1.0,
                "generic",
                data_effects=({"kind": "weapon_damage", "target": "敌军单体", "damage_rate_at_level_10": 1.0},),
            )
            skill._cast_generic(simulator, actor)
            if ally.troops < ally.max_troops:
                hit_ally = True
                break
        assert hit_ally, timing


def test_wanren_zhidi_fear_targets_roll_stun_at_thirty_percent() -> None:
    stunned = 0
    trials = 600
    for seed in range(trials):
        actor = General("张飞", 10000, 300, 100, 200, 180, ["万人之敌"])
        enemy = General("目标", 10000, 180, 180, 200, 100, [])
        enemy.statuses.append(StatusEffect("畏惧", remaining_rounds=2, source_actor="其他来源"))
        simulator = BattleSimulator(Battle(Team("我方", [actor]), Team("敌方", [enemy])), seed=seed)
        simulator.round_no = 1
        skill = skills_for(actor, SkillTiming.ACTIVE)[0]
        skill._cast_generic(simulator, actor)
        stunned += int(enemy.has_status("震慑"))
    observed = stunned / trials
    assert 0.25 <= observed <= 0.35, observed


def test_zero_chance_blocks_non_status_effects() -> None:
    simulator, owner, _, enemy = make_simulator()
    skill = Skill(
        "概率伤害测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=(
            {
                "kind": "weapon_damage",
                "target": "敌军全体",
                "damage_rate_at_level_10": 2.0,
                "trigger_chance": 0.0,
            },
        ),
    )
    skill._cast_generic(simulator, owner)
    assert enemy.troops == enemy.max_troops


def test_round_increasing_effect_chance_caps_at_one() -> None:
    from sanmou_sim.skills import _effect_trigger_chance

    effect = {"trigger_chance": 0.6, "trigger_chance_increase_per_round_at_level_10": 0.1}
    assert _effect_trigger_chance(effect, 1) == 0.6
    assert _effect_trigger_chance(effect, 4) == 0.9
    assert _effect_trigger_chance(effect, 8) == 1.0


def test_explicit_per_target_damage_chance_is_independent() -> None:
    hits = 0
    trials = 600
    for seed in range(trials):
        owner = General("施法者", 10000, 300, 100, 200, 180, [])
        enemies = [General(f"目标{i}", 10000, 180, 180, 200, 100, []) for i in range(2)]
        simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=seed)
        simulator.round_no = 1
        skill = Skill(
            "独立目标测试",
            SkillTiming.ACTIVE,
            1.0,
            "generic",
            data_effects=(
                {
                    "kind": "weapon_damage",
                    "target": "敌军全体",
                    "damage_rate_at_level_10": 1.0,
                    "trigger_chance": 0.5,
                    "independent_judgment_per_target": True,
                },
            ),
        )
        skill._cast_generic(simulator, owner)
        hits += sum(enemy.troops < enemy.max_troops for enemy in enemies)
    observed = hits / (trials * 2)
    assert 0.45 <= observed <= 0.55, observed


def test_structured_zero_chance_damage_does_not_fall_back_to_raw_text() -> None:
    simulator, owner, _, enemy = make_simulator()
    skill = Skill(
        "结构化概率测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        raw_text="对敌军单体造成200%兵刃伤害",
        traits=("兵刃",),
        data_effects=(
            {
                "kind": "weapon_damage",
                "target": "敌军单体",
                "damage_rate_at_level_10": 2.0,
                "trigger_chance": 0.0,
            },
        ),
    )
    skill._cast_generic(simulator, owner)
    assert enemy.troops == enemy.max_troops


def test_random_target_range_is_not_collapsed_to_maximum() -> None:
    observed: set[int] = set()
    for seed in range(30):
        owner = General("施法者", 10000, 200, 200, 200, 200, [])
        enemies = [General(f"目标{i}", 10000, 100, 100, 100, 100, []) for i in range(3)]
        simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=seed)
        skill = Skill("随机人数测试", SkillTiming.ACTIVE, 1.0, "generic")
        observed.add(len(skill._select_targets(simulator, owner, "敌军随机1-2人", True)))
    assert observed == {1, 2}


def test_huju_jiangdong_counts_learned_skill_types() -> None:
    actor = General("孙权", 10000, 200, 200, 200, 200, ["虎踞江东", "运筹帷幄", "风急雨晦"])
    ally = General("队友", 10000, 200, 200, 200, 200, [])
    enemy = General("目标", 10000, 200, 200, 200, 200, [])
    simulator = BattleSimulator(Battle(Team("我方", [actor, ally]), Team("敌方", [enemy])), seed=3)
    simulator.round_no = 1
    skill = skills_for(actor, SkillTiming.COMMAND)[0]
    skill.apply_setup(simulator, actor)
    assert abs(actor.modifier_total("active_chance_bonus") - 0.14) < 1e-9
    assert abs(ally.modifier_total("active_chance_bonus") - 0.14) < 1e-9
    assert abs(actor.modifier_total("combo_chance") - 0.28) < 1e-9


def test_fengji_yuhui_random_bundle_applies_one_or_two_effects_per_general() -> None:
    actor = General("于吉", 9000, 100, 300, 180, 180, ["风急雨晦"])
    ally = General("队友", 9000, 100, 180, 180, 180, [])
    enemy = General("目标", 10000, 100, 100, 100, 100, [])
    actor.troops = 7000
    ally.troops = 7000
    simulator = BattleSimulator(Battle(Team("我方", [actor, ally]), Team("敌方", [enemy])), seed=8)
    simulator.round_no = 1
    skill = skills_for(actor, SkillTiming.ACTIVE)[0]
    skill._cast_generic(simulator, actor)
    for target in (actor, ally):
        applied = int(target.troops > 7000)
        applied += int(target.has_status("技穷免疫"))
        applied += int(target.modifier_total("active_chance_bonus") > 0)
        assert 1 <= applied <= 2


def test_yunxing_yushi_reduces_only_the_current_hit() -> None:
    attacker = General("攻击者", 10000, 400, 100, 200, 100, [])
    owner = General("诸葛亮", 10000, 100, 300, 200, 100, ["云行雨施"])
    simulator = BattleSimulator(Battle(Team("攻方", [attacker]), Team("守方", [owner])), seed=2)
    simulator.round_no = 1
    skills_for(owner, SkillTiming.COMMAND)[0].apply_setup(simulator, owner)
    first = simulator.deal_damage(attacker, owner, 1.0, DamageKind.WEAPON, "测试伤害")
    second = simulator.deal_damage(attacker, owner, 1.0, DamageKind.WEAPON, "测试伤害")
    assert first == 448
    assert second == 448
    assert owner.modifier_total("damage_taken_reduction") == 0


def test_buqu_yizhi_redirects_large_ally_hit_with_reduction() -> None:
    owner = General("周泰", 10000, 200, 100, 400, 100, ["不屈意志"])
    ally = General("队友", 10000, 100, 100, 100, 100, [])
    attacker = General("攻击者", 10000, 900, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("守方", [owner, ally]), Team("攻方", [attacker])), seed=0)
    simulator.round_no = 1
    damage = simulator.deal_damage(attacker, ally, 2.0, DamageKind.WEAPON, "测试伤害")
    assert ally.troops == ally.max_troops
    assert owner.troops == owner.max_troops - damage
    assert damage == 860


def test_buqu_yizhi_prevents_a_lethal_hit() -> None:
    owner = General("周泰", 100, 200, 100, 400, 100, ["不屈意志"], max_troops=10000)
    ally = General("队友", 10000, 100, 100, 100, 100, [])
    attacker = General("攻击者", 10000, 900, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("守方", [owner, ally]), Team("攻方", [attacker])), seed=1)
    simulator.round_no = 1
    damage = simulator.deal_damage(attacker, owner, 5.0, DamageKind.WEAPON, "测试伤害")
    assert damage == 99
    assert owner.troops == 1
    assert any("免疫本次致命伤害" in line for line in simulator.log)


def test_nanjiang_lieren_forces_critical_and_heals_lowest_ally() -> None:
    owner = General("孟获", 8000, 350, 100, 220, 100, ["南疆烈刃"])
    ally = General("队友", 10000, 100, 100, 100, 100, [])
    ally.troops = 5000
    enemy = General("目标", 10000, 100, 100, 150, 100, [])
    enemy.modifiers.append(Modifier("属性降低", "command", -10))
    simulator = BattleSimulator(Battle(Team("我方", [owner, ally]), Team("敌方", [enemy])), seed=4)
    simulator.round_no = 1
    damage = simulator.deal_damage(owner, enemy, 1.0, DamageKind.WEAPON, "测试伤害")
    assert damage == 855
    assert ally.troops == 5000 + int(damage * 0.25)


def test_ignored_reduction_applies_to_reduction_pool_only() -> None:
    attacker = General("攻击者", 10000, 400, 100, 200, 100, [])
    target = General("目标", 10000, 100, 100, 200, 100, [])
    target.modifiers.append(Modifier("减伤", "damage_taken_reduction", 0.50))
    simulator = BattleSimulator(Battle(Team("攻方", [attacker]), Team("守方", [target])), seed=1)
    simulator.round_no = 1
    damage = simulator.deal_damage(
        attacker,
        target,
        1.0,
        DamageKind.WEAPON,
        "测试伤害",
        damage_context={"ignore_damage_reduction": 0.40},
    )
    assert damage == 392


def test_clear_state_suppresses_control_without_removing_it() -> None:
    simulator, owner, _, _ = make_simulator()
    owner.statuses.extend(
        [
            StatusEffect("清醒", remaining_rounds=1),
            StatusEffect("震慑", remaining_rounds=1),
            StatusEffect("技穷", remaining_rounds=1),
            StatusEffect("缴械", remaining_rounds=1),
            StatusEffect("虚弱", remaining_rounds=1),
        ]
    )
    assert not simulator._has_active_control(owner, "震慑")
    assert not simulator._has_active_control(owner, "技穷")
    assert not simulator._has_active_control(owner, "缴械")
    assert simulator._damage_dealt_multiplier(owner, DamageKind.WEAPON, "active") == 1.0
    assert owner.has_status("震慑")


def test_fubing_blocks_half_damage_and_returns_equal_deserters() -> None:
    defender = General("防守者", 10000, 100, 100, 200, 100, [])
    attacker = General("攻击者", 10000, 400, 100, 200, 100, [])
    simulator = BattleSimulator(Battle(Team("守方", [defender]), Team("攻方", [attacker])), seed=1)
    simulator.round_no = 1
    skill = Skill(
        "伏兵测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=(
            {
                "kind": "grant_state",
                "target": "自身",
                "state": "伏兵",
                "amount_current_troop_ratio_at_level_10": 0.05,
            },
        ),
    )
    skill._cast_generic(simulator, defender)
    damage = simulator.deal_damage(attacker, defender, 1.0, DamageKind.WEAPON, "测试伤害")
    assert damage == 280
    assert defender.troops == 9720
    assert attacker.troops == 9720
    assert defender.status("伏兵").payload["amount"] == 220


def test_jueshui_podi_uses_preexisting_flood_branch_only() -> None:
    owner = General("施法者", 10000, 100, 300, 200, 100, ["决水破敌"])
    enemy = General("目标", 10000, 100, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", [enemy])), seed=1)
    simulator.round_no = 1
    skill = skills_for(owner, SkillTiming.ACTIVE)[0]
    skill._cast_generic(simulator, owner)
    first_loss = enemy.max_troops - enemy.troops
    assert first_loss == 560
    assert enemy.has_status("洪水")

    before = enemy.troops
    skill._cast_generic(simulator, owner)
    assert before - enemy.troops > first_loss


def test_xingluo_qibu_applies_formation_and_single_front_board_bonus() -> None:
    owner = General("SP诸葛亮", 10000, 100, 300, 200, 100, ["星罗棋布"], position="front")
    ally_a = General("后排一", 10000, 100, 100, 200, 100, [], position="back")
    ally_b = General("后排二", 10000, 100, 100, 200, 100, [], position="back")
    enemy = General("目标", 10000, 100, 100, 100, 100, [])
    owner.modifiers.append(Modifier("箕形阵", "damage_taken_reduction", 0.06))
    team = Team("我方", [owner, ally_a, ally_b], formation_id="jixing", formation_name="箕形阵")
    simulator = BattleSimulator(Battle(team, Team("敌方", [enemy])), seed=1)
    skills_for(owner, SkillTiming.COMMAND)[0].apply_setup(simulator, owner)
    assert abs(owner.modifier_total("strategy_damage_taken_reduction") - 0.13) < 1e-9
    assert abs(ally_a.modifier_total("strategy_damage_taken_reduction") - 0.10) < 1e-9
    assert any(modifier.source_skill == "星罗棋布" and abs(modifier.value - 0.042) < 1e-9 for modifier in owner.modifiers)
    assert owner.modifier_total("basic_target_weight_override") == 0.85
    assert ally_a.modifier_total("basic_target_weight_override") == 0.075
    assert any("【受击权重】" in entry for entry in simulator.log)
    assert not any("basic target weight override" in entry for entry in simulator.log)
    snapshot = simulator._snapshot_general(owner)
    assert any(modifier["name"] == "受击权重" for modifier in snapshot["modifiers"])


def test_formation_target_weight_is_not_changed_by_current_troops() -> None:
    attacker = General("攻击者", 10000, 200, 200, 200, 200, [])
    full = General("前排满兵", 10000, 200, 200, 200, 200, [], basic_target_weight=0.60)
    low = General("后排残兵", 1, 200, 200, 200, 200, [], max_troops=10000, basic_target_weight=0.20)
    other = General("后排满兵", 10000, 200, 200, 200, 200, [], basic_target_weight=0.20)
    simulator = BattleSimulator(Battle(Team("我方", [attacker]), Team("敌方", [full, low, other])), seed=1)

    assert simulator._target_weight(full) == 0.60
    assert simulator._target_weight(low) == 0.20
    assert simulator._target_weight(other) == 0.20


def test_jiufa_zhongyuan_three_campaigns_settle_deserters_once() -> None:
    owner = General("姜维", 100000, 300, 300, 200, 100, [])
    enemies = [General(f"目标{i}", 100000, 100, 100, 100, 100, []) for i in range(3)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = Skill(
        "九伐中原",
        SkillTiming.COMMAND,
        1.0,
        "generic",
        data_effects=(
            {
                "timing": "每个回合结束时",
                "target": "敌军随机两人",
                "kind": "multi_hit",
                "hit_count_min": 3,
                "hit_count_max": 3,
                "damage_kinds": ["兵刃", "谋略"],
                "damage_rate": 0.01,
            },
            {
                "condition": "累积讨伐3次后",
                "target": "敌军兵力最低单体",
                "kind": "apply_state",
                "state": "逃兵",
                "deserter_formula": {
                    "force_coefficient": 2.4,
                    "intellect_coefficient": 2.4,
                    "constant": -631,
                },
            },
        ),
        raw_text="每个回合结束时进行3次讨伐；累积讨伐3次后使敌军兵力最低单体产生逃兵",
    )

    skill._cast_generic(simulator, owner, event="round_end")

    assert sum("兵刃伤害" in line for line in simulator.log) == 6
    assert sum("谋略伤害" in line for line in simulator.log) == 6
    assert sum("产生 809 逃兵" in line for line in simulator.log) == 1
    assert owner.status("九伐中原-讨伐次数").stacks == 3


def test_mutual_basic_attack_only_owner_ignores_disarm() -> None:
    owner = General("发动者", 10000, 300, 100, 100, 100, [])
    enemy = General("目标", 10000, 300, 100, 100, 100, [])
    owner.statuses.append(StatusEffect("缴械", remaining_rounds=1))
    enemy.statuses.append(StatusEffect("缴械", remaining_rounds=1))
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", [enemy])), seed=1)
    simulator.round_no = 1
    skill = Skill(
        "相互普攻测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=(
            {
                "target": "敌军全体",
                "kind": "mutual_basic_attack",
                "times": 1,
                "self_immune_states_during_exchange": ["缴械"],
            },
        ),
    )

    skill._cast_generic(simulator, owner)

    assert enemy.troops < enemy.max_troops
    assert owner.troops == owner.max_troops


def test_shiquan_cover_uses_actual_holder_without_large_hit_gate() -> None:
    owner = General("施法者", 10000, 100, 100, 200, 100, [])
    holder = General("放权目标", 10000, 100, 100, 200, 100, [])
    attacker = General("攻击者", 10000, 300, 100, 100, 100, [])
    holder.statuses.append(StatusEffect("放权", remaining_rounds=None, source_actor=owner.name))
    simulator = BattleSimulator(Battle(Team("我方", [owner, holder]), Team("敌方", [attacker])), seed=1)
    simulator.round_no = 1
    skill = Skill("释权御下", SkillTiming.COMMAND, 1.0, "generic")
    context = {"target": owner, "incoming_damage": 500}

    skill._cast_special_effect(
        simulator,
        owner,
        {
            "timing": "自身受到伤害时",
            "target": "放权目标",
            "kind": "cover_damage",
            "trigger_chance": 1.0,
        },
        "before_damage_taken",
        context,
    )

    assert context["redirect_target"] is holder


def test_buqu_cover_keeps_large_hit_gate() -> None:
    owner = General("周泰", 10000, 100, 100, 200, 100, [])
    ally = General("队友", 10000, 100, 100, 200, 100, [])
    attacker = General("攻击者", 10000, 300, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner, ally]), Team("敌方", [attacker])), seed=1)
    simulator.round_no = 1
    skill = Skill("不屈意志", SkillTiming.COMMAND, 1.0, "generic")
    context = {"target": ally, "incoming_damage": 500}

    skill._cast_special_effect(
        simulator,
        owner,
        {
            "condition": "队友即将受到高于当前兵力10%的伤害时",
            "target": "队友",
            "kind": "cover_damage",
            "trigger_chance": 1.0,
        },
        "before_damage_taken",
        context,
    )

    assert "redirect_target" not in context


def test_specific_reduction_only_affects_deserter_and_transfer_damage() -> None:
    owner = General("施法者", 10000, 100, 100, 200, 100, [])
    attacker = General("攻击者", 10000, 300, 300, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", [attacker])), seed=1)
    simulator.round_no = 1
    skill = Skill("特定伤害减伤测试", SkillTiming.COMMAND, 1.0, "generic")
    effect = {
        "target": "自身",
        "kind": "specific_damage_taken_reduction",
        "damage_kinds": ["逃兵", "传递伤害"],
        "value": 0.30,
    }

    skill._cast_special_effect(simulator, owner, effect, "setup", {})

    assert owner.modifier_total("deserter_damage_taken_reduction") == 0.30
    assert owner.modifier_total("transfer_damage_taken_reduction") == 0.30
    before = owner.troops
    assert simulator.settle_deserters(attacker, owner, 1000, "逃兵测试") == 700
    assert before - owner.troops == 700
    before = owner.troops
    assert simulator.deal_damage(attacker, owner, 1000, DamageKind.TRANSFER, "传递测试") == 700
    assert before - owner.troops == 700


def test_same_damage_type_reduction_tracks_incoming_damage_kind() -> None:
    owner = General("施法者", 10000, 100, 100, 200, 100, [])
    attacker = General("伤害来源", 10000, 300, 300, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", [attacker])), seed=1)
    simulator.round_no = 1
    skill = Skill("并肩携手测试", SkillTiming.COMMAND, 1.0, "generic")
    effect = {
        "target": "伤害来源",
        "kind": "same_damage_type_dealt_reduction",
        "value": 0.03,
        "duration_rounds": 2,
        "max_stacks": 10,
    }

    skill._cast_special_effect(
        simulator,
        owner,
        effect,
        "before_damage_taken",
        {"attacker": attacker, "target": owner, "kind": DamageKind.WEAPON},
    )
    skill._cast_special_effect(
        simulator,
        owner,
        effect,
        "before_damage_taken",
        {"attacker": attacker, "target": owner, "kind": DamageKind.WEAPON},
    )
    skill._cast_special_effect(
        simulator,
        owner,
        effect,
        "before_damage_taken",
        {"attacker": attacker, "target": owner, "kind": DamageKind.STRATEGY},
    )

    assert abs(attacker.modifier_total("weapon_damage_dealt_reduction") - 0.06) < 1e-9
    assert abs(attacker.modifier_total("strategy_damage_dealt_reduction") - 0.03) < 1e-9
    assert abs(simulator._damage_dealt_multiplier(attacker, DamageKind.WEAPON, "active") - 0.94) < 1e-9
    assert abs(simulator._damage_dealt_multiplier(attacker, DamageKind.STRATEGY, "active") - 0.97) < 1e-9


def test_suyi_yuejian_triggers_once_per_crossed_damage_threshold() -> None:
    owner = General("小乔", 10000, 100, 300, 200, 100, ["素衣约俭"])
    ally_a = General("低兵一", 4000, 100, 100, 100, 100, [], max_troops=10000)
    ally_b = General("低兵二", 5000, 100, 100, 100, 100, [], max_troops=10000)
    attacker = General("攻击者", 10000, 300, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner, ally_a, ally_b]), Team("敌方", [attacker])), seed=1)
    simulator.round_no = 1
    skill = next(skill for timing in SkillTiming for skill in skills_for(owner, timing) if skill.name == "素衣约俭")

    assert not skill.trigger(
        simulator,
        owner,
        "after_damage_taken",
        {"attacker": attacker, "target": ally_a, "damage": 500, "team_damage_taken_before": 0, "team_damage_taken_total": 500},
    )
    assert skill.trigger(
        simulator,
        owner,
        "after_damage_taken",
        {"attacker": attacker, "target": ally_a, "damage": 4000, "team_damage_taken_before": 500, "team_damage_taken_total": 4500},
    )

    assert ally_a.status("素衣").stacks == 2
    assert ally_b.status("素衣").stacks == 2


def test_per_round_first_damage_trigger_only_runs_once() -> None:
    owner = General("孙坚", 10000, 100, 100, 300, 100, ["持军毅重"])
    enemies = [General(f"敌军{i}", 10000, 100, 100, 100, 100, []) for i in range(3)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=2)
    simulator.round_no = 1
    skill = next(skill for timing in SkillTiming for skill in skills_for(owner, timing) if skill.name == "持军毅重")
    context = {"attacker": enemies[0], "target": owner, "kind": DamageKind.WEAPON, "damage": 100}

    assert skill.trigger(simulator, owner, "after_damage_taken", dict(context))
    first_count = sum(
        modifier.source_skill == "持军毅重" and modifier.stat == "damage_taken_increase"
        for enemy in enemies
        for modifier in enemy.modifiers
    )
    assert first_count == 2
    assert not skill.trigger(simulator, owner, "after_damage_taken", dict(context))
    second_count = sum(
        modifier.source_skill == "持军毅重" and modifier.stat == "damage_taken_increase"
        for enemy in enemies
        for modifier in enemy.modifiers
    )
    assert second_count == first_count


def test_bingdong_ruoshen_ten_orders_damage_triggers_only_once() -> None:
    owner = General("武将", 10000, 300, 100, 300, 100, ["兵动若神"])
    enemies = [General(f"敌军{i}", 100000, 100, 100, 100, 100, []) for i in range(2)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = next(skill for timing in SkillTiming for skill in skills_for(owner, timing) if skill.name == "兵动若神")
    owner.statuses.append(
        StatusEffect(
            "军令",
            remaining_rounds=None,
            stacks=9,
            max_stacks=10,
            source_actor=owner.name,
            source_team=owner.team,
            payload={"source_skill": "兵动若神"},
        )
    )

    skill._add_status(simulator, owner, owner, "军令", None, {"kind": "gain_stack", "state": "军令", "stacks": 1})
    first_damage_logs = sum("兵动若神" in line and "兵刃伤害" in line for line in simulator.log)
    skill._add_status(simulator, owner, owner, "军令", None, {"kind": "gain_stack", "state": "军令", "stacks": 1})
    second_damage_logs = sum("兵动若神" in line and "兵刃伤害" in line for line in simulator.log)

    assert first_damage_logs == len(enemies)
    assert second_damage_logs == first_damage_logs


def test_corresponding_highest_attribute_bonus_uses_setup_markers() -> None:
    owner = General("战法持有者", 10000, 100, 100, 100, 100, [])
    multi_highest = General("多项最高", 10000, 300, 200, 300, 100, [])
    intellect_highest = General("智力最高", 10000, 200, 400, 200, 100, [])
    ordinary = General("普通队友", 10000, 150, 150, 150, 100, [])
    attacker = General("攻击者", 10000, 200, 200, 200, 100, [])
    simulator = BattleSimulator(
        Battle(Team("我方", [owner, multi_highest, intellect_highest, ordinary]), Team("敌方", [attacker])),
        seed=1,
    )
    simulator.round_no = 1
    skill = Skill(
        "百战不殆测试",
        SkillTiming.COMMAND,
        1.0,
        "generic",
        data_effects=(
            {
                "timing": "我军统率/智力/武力最高单体受到伤害时",
                "target": "对应属性最高单体",
                "kind": "corresponding_attribute_bonus_flat",
                "trigger_chance": 1.0,
                "value": 7,
                "attributes": ["统率", "智力", "武力"],
                "max_stacks": 8,
            },
        ),
    )

    assert skill.apply_setup(simulator, owner)
    assert multi_highest.has_status("百战不殆-武")
    assert multi_highest.has_status("百战不殆-统")
    assert intellect_highest.has_status("百战不殆-智")
    ordinary.modifiers.extend(
        [
            Modifier("后续武力变化", "force", 1000),
            Modifier("后续智力变化", "intellect", 1000),
            Modifier("后续统率变化", "command", 1000),
        ]
    )
    assert not skill.trigger(
        simulator,
        owner,
        "after_damage_taken",
        {"attacker": attacker, "target": ordinary, "kind": DamageKind.WEAPON, "damage": 100},
    )
    assert skill.trigger(
        simulator,
        owner,
        "after_damage_taken",
        {"attacker": attacker, "target": multi_highest, "kind": DamageKind.WEAPON, "damage": 100},
    )

    assert multi_highest.modifier_total("force") == 7
    assert multi_highest.modifier_total("command") == 7
    assert multi_highest.modifier_total("intellect") == 0
    assert skill.trigger(
        simulator,
        owner,
        "after_damage_taken",
        {"attacker": attacker, "target": intellect_highest, "kind": DamageKind.WEAPON, "damage": 100},
    )
    assert intellect_highest.modifier_total("intellect") == 7
    assert ordinary.modifier_total("force") == 1000


def test_cleansing_negative_state_removes_its_modifier() -> None:
    target = General("目标", 10000, 100, 100, 100, 100, [])
    target.statuses.append(StatusEffect("畏惧", 2, source_actor="敌方", payload={"source_skill": "施加畏惧"}))
    target.modifiers.append(Modifier("施加畏惧:畏惧:易伤", "damage_taken_increase", 0.10, source_skill="施加畏惧"))

    _cleanse_negative_states(target, 1)

    assert not target.has_status("畏惧")
    assert target.modifier_total("damage_taken_increase") == 0


def test_baizhan_locks_target_at_its_command_turn() -> None:
    import sanmou_sim.simulator as simulator_module

    owner = General("百战持有者", 10000, 100, 100, 100, 300, [])
    initial_highest = General("原武力最高", 10000, 200, 100, 100, 200, [])
    later_boosted = General("后续反超", 10000, 180, 100, 100, 100, [])
    enemy = General("对手", 10000, 100, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner, initial_highest, later_boosted]), Team("敌方", [enemy])), seed=1)
    baizhan = Skill(
        "百战不殆", SkillTiming.COMMAND, 1.0, "generic",
        data_effects=({"kind": "corresponding_attribute_bonus_flat", "attributes": ["武力"], "value": 7},),
    )

    class LaterCommandBonus:
        def apply_setup(self, api: BattleSimulator, actor: General) -> bool:
            actor.modifiers.append(Modifier("后续指挥加成", "force", 50))
            return True

        def trigger(self, api: BattleSimulator, actor: General, event: str, context: dict) -> bool:
            return False

    original_skills_for = simulator_module.skills_for

    def ordered_skills(actor: General, timing: SkillTiming) -> list:
        if timing == SkillTiming.COMMAND:
            return [baizhan] if actor is owner else [LaterCommandBonus()] if actor is later_boosted else []
        return []

    try:
        simulator_module.skills_for = ordered_skills
        simulator._apply_setup_phase()
    finally:
        simulator_module.skills_for = original_skills_for

    assert later_boosted.stat("force") == 230
    assert initial_highest.has_status("百战不殆-武")
    assert not later_boosted.has_status("百战不殆-武")


def test_wulie_polu_command_reduction_increases_against_higher_command() -> None:
    owner = General("发动者", 10000, 300, 100, 200, 100, [])
    enemy = General("高统率目标", 10000, 100, 100, 300, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", [enemy])), seed=1)
    simulator.round_no = 1
    skill = Skill(
        "武烈破虏测试",
        SkillTiming.ACTIVE,
        1.0,
        "generic",
        data_effects=(
            {
                "target": "敌军随机单体",
                "kind": "command_reduction_flat",
                "value": 40,
                "duration_rounds": 2,
                "effect_increase_if_target_command_higher_than_self": 0.5,
            },
        ),
    )

    skill._cast_generic(simulator, owner)

    assert enemy.modifier_total("command") == -60


def test_huaifeng_xiance_uses_strategy_holder_and_clears_wulue() -> None:
    class AlwaysLockRandom:
        @staticmethod
        def random() -> float:
            return 0.0

    owner = General("战法持有者", 10000, 200, 300, 400, 100, ["怀锋献策"], position="front")
    holder = General("施策队友", 10000, 300, 300, 200, 100, [], position="back")
    low_force = General("武力最低", 100000, 1, 500, 200, 100, [])
    low_intellect = General("智力最低", 100000, 500, 1, 200, 100, [])
    simulator = BattleSimulator(
        Battle(Team("我方", [owner, holder]), Team("敌方", [low_force, low_intellect])),
        seed=1,
    )
    skill = next(skill for timing in SkillTiming for skill in skills_for(owner, timing) if skill.name == "怀锋献策")

    assert skill.apply_setup(simulator, owner)
    assert holder.has_status("施策")
    assert abs(holder.modifier_total("innate_damage_taken_reduction") - 0.10) < 1e-9

    simulator.round_no = 1
    strategy_context = {
        "attacker": holder,
        "target": low_force,
        "kind": DamageKind.STRATEGY,
        "source": "其他谋略战法",
    }
    assert skill.trigger(simulator, owner, "before_damage_dealt", dict(strategy_context))
    assert not holder.has_status("武略")
    assert skill.trigger(
        simulator,
        owner,
        "before_damage_dealt",
        {"attacker": holder, "target": low_force, "kind": DamageKind.WEAPON, "source": "其他兵刃战法"},
    )
    assert holder.has_status("文韬")
    assert skill.trigger(simulator, owner, "before_damage_dealt", dict(strategy_context))
    assert not holder.has_status("文韬")
    assert holder.status("武略").stacks == 1

    simulator.round_no = 2
    simulator.rng = AlwaysLockRandom()
    assert skill.trigger(simulator, owner, "action_start", {"actor": holder})

    assert not holder.has_status("武略")
    weapon_logs = [line for line in simulator.log if "怀锋献策" in line and "兵刃伤害" in line]
    strategy_logs = [line for line in simulator.log if "怀锋献策" in line and "谋略伤害" in line]
    assert len(weapon_logs) == 2 and all("武力最低" in line and "令 施策队友" in line for line in weapon_logs)
    assert len(strategy_logs) == 2 and all("智力最低" in line and "令 施策队友" in line for line in strategy_logs)


def test_shensi_duxing_clear_removes_state_derived_modifiers() -> None:
    owner = General("诸葛亮", 10000, 100, 300, 200, 100, ["慎思笃行"])
    holder = General("笃行持有者", 10000, 300, 200, 200, 100, [])
    enemy = General("目标", 10000, 100, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner, holder]), Team("敌方", [enemy])), seed=1)
    simulator.round_no = 1
    skill = next(skill for timing in SkillTiming for skill in skills_for(owner, timing) if skill.name == "慎思笃行")
    gain = next(effect for effect in skill.data_effects if effect.get("kind") == "gain_stack")
    clear = next(effect for effect in skill.data_effects if effect.get("kind") == "clear_state_stacks")

    skill._add_status(simulator, holder, owner, "笃行", None, gain)
    skill._add_status(simulator, holder, owner, "笃行", None, gain)
    assert holder.status("笃行").stacks == 2
    assert holder.modifier_total("damage_taken_reduction") > 0
    assert holder.modifier_total("critical_damage_bonus") > 0

    skill._cast_special_effect(simulator, owner, clear, "round_end", {})

    assert not holder.has_status("笃行")
    assert holder.modifier_total("damage_taken_reduction") == 0
    assert holder.modifier_total("critical_damage_bonus") == 0
    assert holder.modifier_total("strategy_critical_damage_bonus") == 0


def test_shiquan_intent_stacks_are_consumed_after_each_attack() -> None:
    owner = General("曹操", 10000, 100, 300, 300, 100, ["释权御下"])
    holder = General("放权目标", 10000, 300, 100, 200, 100, [])
    enemy = General("目标", 100000, 100, 100, 100, 100, [])
    holder.statuses.extend(
        [
            StatusEffect("放权", remaining_rounds=None, source_actor=owner.name, payload={"source_skill": "释权御下"}),
            StatusEffect("旨意", remaining_rounds=None, stacks=3, source_actor=owner.name, payload={"source_skill": "释权御下"}),
        ]
    )
    simulator = BattleSimulator(Battle(Team("我方", [owner, holder]), Team("敌方", [enemy])), seed=1)
    simulator.round_no = 1
    skill = next(skill for timing in SkillTiming for skill in skills_for(owner, timing) if skill.name == "释权御下")
    damage_effect = next(
        effect
        for effect in skill.data_effects
        if effect.get("kind") == "damage" and "旨意" in str(effect.get("condition", ""))
    )

    skill._cast_generic(simulator, owner, effects=(damage_effect,), event="round_end")

    damage_logs = [line for line in simulator.log if "释权御下" in line and "造成" in line and "伤害" in line]
    assert len(damage_logs) == 3
    assert all("令 放权目标" in line for line in damage_logs)
    assert not holder.has_status("旨意")


def test_lianhuan_transfer_uses_original_attacker_and_excludes_hit_target() -> None:
    owner = General("庞统", 10000, 100, 300, 100, 100, ["连环计"])
    attacker = General("原始伤害来源", 10000, 300, 100, 100, 100, [])
    chained = General("连环目标", 10000, 100, 100, 100, 100, [])
    ally_a = General("队友一", 10000, 100, 100, 100, 100, [])
    ally_b = General("队友二", 10000, 100, 100, 100, 100, [])
    chained.statuses.append(
        StatusEffect(
            "连环",
            remaining_rounds=1,
            source_actor=owner.name,
            source_team=owner.team,
            payload={"source_skill": "连环计"},
        )
    )
    simulator = BattleSimulator(
        Battle(Team("我方", [owner, attacker]), Team("敌方", [chained, ally_a, ally_b])),
        seed=1,
    )
    simulator.round_no = 1
    skill = next(skill for timing in SkillTiming for skill in skills_for(owner, timing) if skill.name == "连环计")

    assert skill.trigger(
        simulator,
        owner,
        "after_damage_taken",
        {"attacker": attacker, "target": chained, "damage": 1000, "kind": DamageKind.WEAPON, "source": "测试伤害"},
    )

    assert chained.troops == chained.max_troops
    assert ally_a.troops == ally_a.max_troops - 250
    assert ally_b.troops == ally_b.max_troops - 250
    transfer_logs = [line for line in simulator.log if "连环计" in line and "传递伤害" in line]
    assert len(transfer_logs) == 2
    assert all("令 原始伤害来源" in line for line in transfer_logs)


def test_chengjian_touxi_secondary_target_is_primary_targets_ally() -> None:
    owner = General("发动者", 10000, 100, 300, 100, 100, ["乘间投隙"])
    enemies = [General(f"敌军{i}", 100000, 100, 100, 100, 100, []) for i in range(3)]
    for enemy in enemies:
        enemy.statuses.append(StatusEffect("混乱", remaining_rounds=1))
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = next(skill for timing in SkillTiming for skill in skills_for(owner, timing) if skill.name == "乘间投隙")

    skill._cast_generic(simulator, owner, event="cast")

    damaged = [enemy for enemy in enemies if enemy.troops < enemy.max_troops]
    assert len(damaged) == 2
    losses = sorted(enemy.max_troops - enemy.troops for enemy in damaged)
    assert losses[0] < losses[1]


def test_yingshi_langgu_grants_layout_states_not_negative_fallback_states() -> None:
    owner = General("司马懿", 10000, 100, 300, 200, 100, ["鹰视狼顾"])
    enemies = [General(f"目标{i}", 10000, 100, 100, 100, 100, []) for i in range(2)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=2)
    simulator.round_no = 1
    skill = skills_for(owner, SkillTiming.ACTIVE)[0]
    skill._cast_generic(simulator, owner)
    layout_states = [status.name for status in owner.statuses if status.name.startswith("布阵")]
    assert 1 <= len(set(layout_states)) <= 2
    assert not any(owner.has_status(state) for state in ("焚烧", "中毒", "畏惧", "技穷", "缴械", "虚弱", "断粮"))


def test_ziwu_qimou_settles_bleed_once_at_nine_stacks() -> None:
    owner = General("魏延", 10000, 300, 100, 200, 100, ["子午奇谋"])
    target = General("目标", 10000, 100, 100, 200, 100, [])
    owner.statuses.append(StatusEffect("狂骨", remaining_rounds=None, stacks=9, max_stacks=15))
    target.statuses.append(
        StatusEffect(
            "流血",
            remaining_rounds=2,
            stacks=2,
            max_stacks=5,
            source_actor=owner.name,
            payload={"power": 0.60, "source_skill": "子午奇谋"},
        )
    )
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", [target])), seed=1)
    simulator.round_no = 1
    skill = skills_for(owner, SkillTiming.COMMAND)[0]
    effect = next(item for item in skill.data_effects if item.get("kind") == "settle_state_damage")
    context = {"all_generals": [owner, target]}
    skill._cast_special_effect(simulator, owner, effect, "state_gained", context)
    after_first = target.troops
    skill._cast_special_effect(simulator, owner, effect, "state_gained", context)
    assert after_first < target.max_troops
    assert target.troops == after_first


def test_mingqi_xushi_recalculates_after_each_target_and_settles_damage_inline() -> None:
    enemies = [General(f"目标{i}", 10000, 100, 100, 100, 100, []) for i in range(2)]
    owner = General("发动者", 10000, 100, 100, 100, 100, ["明其虚实"])
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = Skill(
        "明其虚实", SkillTiming.ACTIVE, 1.0, "generic",
        data_effects=(
            {"kind": "steal_stat", "target": "敌军随机两人", "stats": ["智力", "统率"],
             "duration_rounds": 2, "calibrated_formula": {"stat": "智力", "intercept": 0, "coefficient": 0.1}},
            {"kind": "strategy_damage", "target": "敌军随机两人", "damage_rate": 1.0},
        ),
    )
    skill._cast_generic(simulator, owner)
    first, second = [line for line in simulator.log if "明其虚实 对" in line and "伤害" in line]
    assert first in simulator.log and second in simulator.log
    assert owner.stat("intellect") == 121
    assert sorted(enemy.stat("intellect") for enemy in enemies) == [89, 90]
    first_damage_index = simulator.log.index(first)
    second_target = next(enemy for enemy in enemies if enemy.name in second)
    second_target_first_log = next(i for i, line in enumerate(simulator.log) if second_target.name in line)
    assert first_damage_index < second_target_first_log


def test_caocuan_and_jibian_resolve_nested_damage_before_next_caocuan() -> None:
    import dataclasses
    import sanmou_sim.simulator as simulator_module

    owner = General("诸葛亮", 100000, 100, 300, 100, 100, ["草船借箭", "机变无穷"])
    enemy = General("目标", 100000, 100, 100, 100, 100, [])
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", [enemy])), seed=1)
    simulator.round_no = 1
    grass = skills_for(owner, SkillTiming.COMMAND)[0]
    jibian = skills_for(owner, SkillTiming.PASSIVE)[0]
    grass = dataclasses.replace(grass, data_effects=(dict(grass.data_effects[1], trigger_chance=1),))
    jibian = dataclasses.replace(jibian, data_effects=tuple(dict(effect, trigger_chance_at_level_10=1) for effect in jibian.data_effects))
    original = simulator_module.skills_for
    simulator_module.skills_for = lambda actor, timing: (
        [grass] if actor is owner and timing == SkillTiming.COMMAND else
        [jibian] if actor is owner and timing == SkillTiming.PASSIVE else []
    )
    try:
        simulator.deal_damage(owner, enemy, 1.0, DamageKind.STRATEGY, "草船借箭")
    finally:
        simulator_module.skills_for = original
    triggers = [line for line in simulator.log if "触发 机变无穷" in line or "触发 草船借箭" in line]
    assert triggers[:2] == ["诸葛亮 触发 机变无穷", "诸葛亮 触发 草船借箭"]
    assert len([line for line in triggers if "触发 机变无穷" in line]) == 4
    assert len([line for line in triggers if "触发 草船借箭" in line]) == 5


def test_multi_target_effects_finish_one_target_before_next() -> None:
    owner = General("张飞", 10000, 300, 100, 100, 100, ["万人之敌"])
    enemies = [General(f"目标{i}", 100000, 100, 100, 100, 100, []) for i in range(2)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = skills_for(owner, SkillTiming.ACTIVE)[0]
    skill._cast_generic(simulator, owner)
    damage_lines = [(i, line) for i, line in enumerate(simulator.log) if "万人之敌 对" in line and "伤害" in line]
    assert len(damage_lines) == 2
    first_target = next(enemy for enemy in enemies if enemy.name in damage_lines[0][1])
    first_fear = next(i for i, line in enumerate(simulator.log) if line == f"{first_target.name} 获得 畏惧")
    assert damage_lines[0][0] < first_fear < damage_lines[1][0]


def test_compound_damage_finishes_both_kinds_per_target() -> None:
    owner = General("发动者", 10000, 300, 300, 100, 100, [])
    enemies = [General(f"目标{i}", 100000, 100, 100, 100, 100, []) for i in range(2)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = Skill(
        "复合伤害测试", SkillTiming.ACTIVE, 1.0, "generic",
        data_effects=({"kind": "weapon_and_strategy_damage", "target": "敌军全体", "damage_rate": 1.0},),
    )
    skill._cast_generic(simulator, owner)
    damage_lines = [line for line in simulator.log if "复合伤害测试 对" in line and "伤害" in line]
    assert len(damage_lines) == 4
    assert enemies[0].name in damage_lines[0] and enemies[0].name in damage_lines[1]
    assert enemies[1].name in damage_lines[2] and enemies[1].name in damage_lines[3]
    assert "兵刃" in damage_lines[0] and "谋略" in damage_lines[1]


def test_qiaoli_tianzai_handles_enemy_condition_before_next_target() -> None:
    owner = General("发动者", 10000, 100, 300, 100, 100, ["巧利天灾"])
    ally = General("友军", 10000, 100, 100, 100, 100, [])
    enemies = [General(f"敌军{i}", 100000, 100, 100, 100, 100, []) for i in range(2)]
    for enemy in enemies:
        enemy.statuses.append(StatusEffect("火攻", 2))
    simulator = BattleSimulator(Battle(Team("我方", [owner, ally]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = skills_for(owner, SkillTiming.ACTIVE)[0]
    skill._cast_generic(simulator, owner)
    damage_lines = [(i, line) for i, line in enumerate(simulator.log) if "巧利天灾 对" in line and "伤害" in line]
    assert len(damage_lines) == 3
    assert all(not ally.has_status(state) for state in ("混乱", "缴械", "技穷"))
    assert all(enemy.troops < enemy.max_troops for enemy in enemies)


def test_multi_hit_settles_both_damage_kinds_per_target() -> None:
    owner = General("发动者", 10000, 300, 300, 100, 100, [])
    enemies = [General(f"目标{i}", 100000, 100, 100, 100, 100, []) for i in range(2)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = Skill(
        "连击测试", SkillTiming.ACTIVE, 1.0, "generic",
        data_effects=({"kind": "multi_hit", "target": "敌军随机两人", "damage_kinds": ["兵刃", "谋略"],
                       "hit_count_min": 1, "hit_count_max": 1, "damage_rate": 1.0},),
    )
    skill._cast_generic(simulator, owner)
    damage_lines = [line for line in simulator.log if "连击测试 对" in line and "伤害" in line]
    assert len(damage_lines) == 4
    assert any(enemy.name in damage_lines[0] and enemy.name in damage_lines[1] for enemy in enemies)
    assert any(enemy.name in damage_lines[2] and enemy.name in damage_lines[3] for enemy in enemies)
    assert not any(enemy.name in damage_lines[0] and enemy.name in damage_lines[2] for enemy in enemies)


def test_second_target_reads_state_changed_by_first_targets_reaction() -> None:
    owner = General("发动者", 10000, 300, 100, 100, 100, [])
    enemies = [General(f"目标{i}", 100000, 100, 100, 100, 100, []) for i in range(2)]

    class ReactiveSimulator(BattleSimulator):
        def _trigger_event(self, event: str, context: dict | None = None) -> dict:
            if event == "after_damage_dealt" and not any(enemy.has_status("畏惧") for enemy in enemies):
                untouched = next(enemy for enemy in enemies if enemy is not context["target"])
                untouched.statuses.append(StatusEffect("畏惧", 2))
            return super()._trigger_event(event, context)

    simulator = ReactiveSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skill = Skill(
        "逐目标读取测试", SkillTiming.ACTIVE, 1.0, "generic",
        data_effects=({"kind": "weapon_damage", "target": "敌军全体", "damage_rate": 1.0,
                       "damage_rate_bonus_if_target_has_state": "畏惧", "damage_rate_bonus": 1.0},),
    )
    skill._cast_generic(simulator, owner)
    losses = [enemy.max_troops - enemy.troops for enemy in enemies]
    assert max(losses) > min(losses) * 1.5


def test_xiaoyong_wuqian_finishes_exchange_and_extra_hit_per_target() -> None:
    owner = General("发动者", 100000, 300, 100, 100, 100, ["骁勇无前"])
    enemies = [General(f"目标{i}", 100000, 100, 100, 100, 100, []) for i in range(2)]
    simulator = BattleSimulator(Battle(Team("我方", [owner]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    skills_for(owner, SkillTiming.ACTIVE)[0]._cast_generic(simulator, owner)
    extra_hits = [(i, line) for i, line in enumerate(simulator.log) if "使用 骁勇无前 对" in line]
    assert len(extra_hits) == 2
    first_target = next(enemy for enemy in enemies if enemy.name in extra_hits[0][1])
    second_target = next(enemy for enemy in enemies if enemy is not first_target)
    second_exchange = next(i for i, line in enumerate(simulator.log) if f"普通攻击 对 {second_target.name}" in line)
    assert extra_hits[0][0] < second_exchange < extra_hits[1][0]


def test_innate_fire_and_flood_trigger_menghuo_per_target() -> None:
    class AlwaysTrigger(Random):
        def random(self) -> float:
            return 0.0

    for name, state, stat in (("苦肉计", "火攻", "intellect"), ("风急雨晦", "洪水", "command")):
        owner = General("自带战法发动者", 100000, 300, 300, 200, 100, [name])
        menghuo = General("孟获", 100000, 500, 100, 200, 180, ["雄护南疆"])
        ally = General("队友", 100000, 100, 100, 100, 100, [])
        enemies = [General(f"敌军{i}", 100000, 100, 100, 100, 100, []) for i in range(3)]
        simulator = BattleSimulator(Battle(Team("我方", [owner, menghuo, ally]), Team("敌方", enemies)), seed=1)
        simulator.round_no = 1
        simulator.rng = AlwaysTrigger()
        skills_for(owner, SkillTiming.ACTIVE)[0]._cast_generic(simulator, owner)
        affected = [enemy for enemy in enemies if enemy.has_status(state)]
        assert affected
        triggers = [entry for entry in simulator.log if entry == "孟获 触发 雄护南疆"]
        assert len(triggers) == len(affected)
        for enemy in affected:
            assert enemy.stat(stat) < 100


def test_non_attribute_debuffs_and_immune_states_do_not_trigger_menghuo() -> None:
    class AlwaysTrigger(Random):
        def random(self) -> float:
            return 0.0

    owner = General("发动者", 100000, 100, 300, 100, 100, ["状态测试"])
    menghuo = General("孟获", 100000, 500, 100, 200, 180, ["雄护南疆"])
    enemies = [General(f"敌军{i}", 100000, 100, 100, 100, 100, []) for i in range(3)]
    enemies[0].statuses.append(StatusEffect("火攻免疫", 2))
    simulator = BattleSimulator(Battle(Team("我方", [owner, menghuo]), Team("敌方", enemies)), seed=1)
    simulator.round_no = 1
    simulator.rng = AlwaysTrigger()
    skill = Skill("状态测试", SkillTiming.ACTIVE, 1.0, "generic")
    for state in ("畏惧", "妖术"):
        skill._cast_generic(simulator, owner, effects=({"kind": "apply_state", "target": "敌军全体", "state": state},))
    assert not any(entry == "孟获 触发 雄护南疆" for entry in simulator.log)
    skill._cast_generic(simulator, owner, effects=({"kind": "apply_state", "target": "敌军全体", "state": "火攻"},))
    assert not enemies[0].has_status("火攻")
    assert enemies[0].stat("intellect") == 100
    assert sum(entry == "孟获 触发 雄护南疆" for entry in simulator.log) == 2
    other_skill = Skill("非自带火攻", SkillTiming.ACTIVE, 1.0, "generic")
    other_skill._cast_generic(simulator, owner, effects=({"kind": "apply_state", "target": "敌军全体", "state": "火攻"},))
    assert sum(entry == "孟获 触发 雄护南疆" for entry in simulator.log) == 2


def main() -> None:
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"rules regression ok: {len(tests)}")


if __name__ == "__main__":
    main()
