from sanmou_sim.models import Battle, General, Team
from sanmou_sim.simulator import BattleSimulator
from sanmou_sim.skills import SkillTiming, skills_for


def _simulator() -> tuple[BattleSimulator, General]:
    owner = General("皇甫嵩", 10000, 100, 100, 300, 100, ["兵动若神"])
    ally = General("队友", 10000, 100, 100, 100, 90, [])
    enemy = General("敌军", 10000, 100, 100, 100, 80, [])
    simulator = BattleSimulator(Battle(Team("我军", [owner, ally]), Team("敌军", [enemy])), seed=1)
    simulator._apply_setup_phase()
    simulator._initialize_command_thresholds()
    return simulator, owner


def _skill(owner: General):
    return next(skill for skill in skills_for(owner, SkillTiming.COMMAND) if skill.name == "兵动若神")


def test_bingdong_threshold_rewards_each_absolute_level_once() -> None:
    simulator, owner = _simulator()
    skill = _skill(owner)
    effect = {"kind": "stat_bonus", "target": "自身", "state": "测试", "stackable": True}

    skill._apply_modifier(simulator, owner, [owner], "command", 60, effect=effect)
    assert owner.status("军令") is not None
    assert owner.status("军令").stacks == 1
    assert simulator.command_thresholds[owner.name]["awarded"] == 1

    # Dropping below the threshold and returning to it must not reward again.
    skill._apply_modifier(
        simulator, owner, [owner], "command", -85, effect={"kind": "temporary_buff", "condition": "drop"}
    )
    skill._apply_modifier(
        simulator, owner, [owner], "command", 85, effect={"kind": "temporary_buff", "condition": "rise"}
    )
    assert owner.status("军令").stacks == 1

    # Reaching the next absolute threshold rewards exactly one more order.
    skill._apply_modifier(simulator, owner, [owner], "command", 35, effect=effect)
    assert owner.status("军令").stacks == 2
    assert simulator.command_thresholds[owner.name]["awarded"] == 2


def test_bingdong_threshold_is_initialized_after_setup_effects() -> None:
    simulator, owner = _simulator()
    baseline = owner.stat("command")
    assert simulator.command_thresholds[owner.name]["baseline"] == baseline
    assert simulator.command_thresholds[owner.name]["awarded"] == 0
