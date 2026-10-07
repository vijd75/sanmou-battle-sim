from __future__ import annotations

import argparse
from pathlib import Path

from .simulator import BattleSimulator, load_battle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Sanmou-style battle simulation.")
    parser.add_argument("config", type=Path, help="Path to a battle JSON file.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible battles.")
    parser.add_argument("--campaign", action="store_true", help="Run repeated draw battles until a side is wiped out.")
    parser.add_argument("--max-battles", type=int, default=8, help="Maximum battles in campaign mode.")
    args = parser.parse_args()

    battle = load_battle(args.config)
    simulator = BattleSimulator(battle, seed=args.seed)
    if args.campaign:
        results = simulator.run_campaign(max_battles=args.max_battles)
        for index, result in enumerate(results, 1):
            print(f"第 {index} 局")
            _print_result(result)
            print()
    else:
        _print_result(simulator.run())


def _print_result(result) -> None:
    print(f"胜者: {result.winner_name}")
    print(f"回合数: {result.rounds}")
    print()
    print("剩余兵力:")
    for team in result.teams:
        print(f"- {team.name}: {team.total_troops}")
        for general in team.generals:
            status = "阵亡" if not general.is_alive else "存活"
            print(
                f"  - {general.name}: {general.troops}/{general.max_troops} "
                f"伤兵{general.wounded_troops} 死兵{general.dead_troops} ({status})"
            )
    print()
    print("战法统计:")
    for stat in sorted(result.stats, key=lambda item: (item.team, item.actor, -(item.damage + item.healing), item.source)):
        print(
            f"- {stat.team} {stat.actor} / {stat.source}: "
            f"发动{stat.activations}次 伤害{stat.damage} 治疗{stat.healing}"
        )
    print()
    print("战报:")
    for line in result.log:
        print(line)


if __name__ == "__main__":
    main()
