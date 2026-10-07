import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sanmou_sim.models import Battle, General, Team
from sanmou_sim.simulator import BattleSimulator


def make_battle() -> Battle:
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


def main() -> None:
    first = BattleSimulator(make_battle(), seed=11).run()
    second = BattleSimulator(make_battle(), seed=11).run()

    assert first.winner_name == second.winner_name
    assert first.log == second.log
    assert first.rounds <= 8
    assert first.winner_name in {"A", "B", "平局"}
    assert first.log
    print("smoke ok")


if __name__ == "__main__":
    main()
