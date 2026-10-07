from sanmou_sim.models import Battle, DamageKind, General, Modifier, StatusEffect, Team
from sanmou_sim.simulator import BattleSimulator


def test_battle_is_reproducible_with_seed() -> None:
    first = BattleSimulator(_battle(), seed=11).run()
    second = BattleSimulator(_battle(), seed=11).run()

    assert first.winner_name == second.winner_name
    assert first.log == second.log


def test_battle_produces_a_winner_or_draw_after_eight_rounds() -> None:
    result = BattleSimulator(_battle(), seed=3).run()

    assert result.rounds <= 8
    assert result.winner_name in {"A", "B", "平局"}
    assert result.log


def test_eight_round_survivors_are_a_draw_even_with_uneven_troops() -> None:
    battle = Battle(
        team_a=Team("A", [General("A1", 100000, 100, 100, 100, 100, [])]),
        team_b=Team("B", [General("B1", 90000, 100, 100, 100, 100, [])]),
        max_rounds=1,
    )

    result = BattleSimulator(battle, seed=1).run()

    assert result.winner_name == "平局"


def test_weapon_damage_uses_current_fitted_base_formula() -> None:
    attacker = General("A1", 10000, 100, 100, 100, 100, [])
    defender = General("B1", 10000, 100, 100, 100, 100, [])
    battle = Battle(Team("A", [attacker]), Team("B", [defender]))
    simulator = BattleSimulator(battle, seed=1)

    damage = simulator.deal_damage(attacker, defender, 1.0, DamageKind.WEAPON, "测试")

    assert damage == 318
    assert defender.troops == 9682
    assert defender.dead_troops == 63
    assert defender.wounded_troops == 255


def test_damage_taken_reduction_has_diminishing_returns_like_evasion() -> None:
    attacker = General("A1", 10000, 100, 100, 100, 100, [])
    defender = General("B1", 10000, 100, 100, 100, 100, [])
    defender.modifiers.append(Modifier("减伤一", "damage_taken_reduction", 0.50))
    defender.modifiers.append(Modifier("减伤二", "damage_taken_reduction", 0.50))
    battle = Battle(Team("A", [attacker]), Team("B", [defender]))
    simulator = BattleSimulator(battle, seed=1)

    damage = simulator.deal_damage(attacker, defender, 1.0, DamageKind.WEAPON, "测试")

    assert damage == 79


def test_evasion_does_not_consume_resist() -> None:
    attacker = General("A1", 10000, 100, 100, 100, 100, [])
    defender = General("B1", 10000, 100, 100, 100, 100, [], evasion_chance=1.0)
    defender.add_status(StatusEffect("抵御", stacks=1, max_stacks=2, payload={"damage_reduction": 0.70}))
    battle = Battle(Team("A", [attacker]), Team("B", [defender]))
    simulator = BattleSimulator(battle, seed=1)

    damage = simulator.deal_damage(attacker, defender, 1.0, DamageKind.WEAPON, "测试")

    assert damage == 0
    assert defender.status("抵御") is not None
    assert defender.status("抵御").stacks == 1


def test_result_tracks_damage_by_actor_and_source() -> None:
    result = BattleSimulator(_battle(), seed=3).run()

    stat = next(item for item in result.stats if item.source == "普通攻击")

    assert stat.actor
    assert stat.activations > 0
    assert stat.damage > 0


def test_result_keeps_zero_damage_skill_with_activation_count() -> None:
    actor = General("A1", 10000, 100, 100, 100, 100, ["披坚执锐"])
    battle = Battle(Team("A", [actor]), Team("B", [General("B1", 10000, 100, 100, 100, 100, [])]), max_rounds=1)

    result = BattleSimulator(battle, seed=1).run()

    stat = next(item for item in result.stats if item.actor == "A1" and item.source == "披坚执锐")
    assert stat.activations == 1
    assert stat.damage == 0
    assert stat.healing == 0


def test_healing_is_tracked_by_actor_and_source() -> None:
    actor = General("A1", 10000, 100, 180, 100, 100, [])
    target = General("A2", 8000, 100, 100, 100, 100, [], max_troops=10000, wounded_troops=2000)
    battle = Battle(Team("A", [actor, target]), Team("B", [General("B1", 10000, 100, 100, 100, 100, [])]))
    simulator = BattleSimulator(battle, seed=1)

    amount = simulator.heal(actor, target, 1.0, "测试治疗")

    assert amount > 0
    assert simulator.source_stats[("A", "A1", "测试治疗")].healing == amount


def _battle() -> Battle:
    return Battle(
        team_a=Team(
            "A",
            [
                General("A1", 3000, 160, 90, 130, 140, ["破阵猛攻"]),
                General("A2", 3000, 150, 80, 120, 120, ["乘胜追击"]),
            ],
        ),
        team_b=Team(
            "B",
            [
                General("B1", 3000, 120, 160, 120, 130, ["运筹帷幄"]),
                General("B2", 3000, 155, 70, 140, 110, ["披坚执锐"]),
            ],
        ),
    )
