import csv
import sqlite3
from pathlib import Path

from tools.damage_db import import_data


def test_import_is_idempotent_and_preserves_factors(tmp_path: Path) -> None:
    csv_path = tmp_path / "events.csv"
    db_path = tmp_path / "damage.sqlite"
    headers = [
        "战报", "事件序号", "原文行号", "攻击者", "目标", "攻击者兵种", "目标兵种",
        "攻击者武力", "攻击者当前兵力", "攻击者最大兵力", "攻击者破甲", "攻击者看破",
        "攻击者增伤", "目标净减伤", "兵种乘区", "是否抵御", "抵御乘区", "是否奇谋",
        "奇谋乘区", "是否击杀截断", "实测伤害", "攻击者状态JSON", "目标状态JSON", "原始文本",
    ]
    row = {
        "战报": "battle-1", "事件序号": "1", "原文行号": "25", "攻击者": "测试甲", "目标": "测试乙",
        "攻击者兵种": "骑兵", "目标兵种": "盾兵", "攻击者武力": "300.5", "攻击者当前兵力": "9000",
        "攻击者最大兵力": "11000", "攻击者破甲": "16.96", "攻击者看破": "0", "攻击者增伤": "12",
        "目标净减伤": "-5", "兵种乘区": "1.13", "是否抵御": "False", "抵御乘区": "1.0",
        "是否奇谋": "True", "奇谋乘区": "1.5", "是否击杀截断": "False",
        "实测伤害": "456", "攻击者状态JSON": '{"兵种":"枪兵","兵力":9000,"最大兵力":11000}',
        "目标状态JSON": '{"兵种":"盾兵","统率":300}', "原始文本": "测试伤害记录",
    }
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)

    first = import_data(csv_path, db_path, reference_files={})
    second = import_data(csv_path, db_path, reference_files={})
    assert first["rows"] == second["rows"] == 1

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM damage_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 2
        assert conn.execute("SELECT observed_damage FROM damage_events").fetchone()[0] == 456
        assert conn.execute("SELECT numeric_value FROM event_factors WHERE factor_name='攻击者破甲'").fetchone()[0] == 16.96
        assert conn.execute("SELECT troop_type FROM event_snapshots WHERE side='attacker'").fetchone()[0] == "骑兵"
        assert "枪兵" in conn.execute("SELECT raw_json FROM event_snapshots WHERE side='attacker'").fetchone()[0]
        assert conn.execute("SELECT COUNT(*) FROM data_quality_issues WHERE code LIKE '%troop_type_conflict'").fetchone()[0] == 0

