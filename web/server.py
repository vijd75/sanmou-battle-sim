from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sanmou_sim.simulator import BattleSimulator, battle_from_dict  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/web/index.html")
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/simulate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            battle = battle_from_dict(payload["battle"])
            seed = payload.get("seed")
            simulator = BattleSimulator(battle, seed=int(seed) if seed not in (None, "") else None)
            result = simulator.run()
            self._send_json(result_to_dict(result))
        except Exception as error:
            self._send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "winner_name": result.winner_name,
        "rounds": result.rounds,
        "teams": [team_to_dict(team) for team in result.teams],
        "log": result.log,
        "log_entries": result.log_entries,
        "stats": [stat_to_dict(stat) for stat in result.stats],
        "snapshots": result.snapshots,
    }


def team_to_dict(team: Any) -> dict[str, Any]:
    return {
        "name": team.name,
        "total_troops": team.total_troops,
        "max_troops": team.max_troops,
        "troop_loss": team.troop_loss,
        "formation_id": team.formation_id,
        "formation_name": team.formation_name,
        "generals": [
            {
                "name": general.name,
                "troops": general.troops,
                "max_troops": general.max_troops,
                "wounded_troops": general.wounded_troops,
                "dead_troops": general.dead_troops,
                "is_alive": general.is_alive,
                "troop_type": general.troop_type,
                "skills": list(general.skills),
            }
            for general in team.generals
        ],
    }


def stat_to_dict(stat: Any) -> dict[str, Any]:
    return {
        "team": stat.team,
        "actor": stat.actor,
        "source": stat.source,
        "activations": stat.activations,
        "damage": stat.damage,
        "healing": stat.healing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Sanmou battle configurator and simulator API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving http://{args.host}:{args.port}/web/index.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
