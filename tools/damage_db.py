#!/usr/bin/env python3
"""Import the canonical all-damage CSV and simulator reference data into SQLite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = Path(
    r"D:\battlelog-capture-assistant\csv_output\拟合结果\兵力系数\全部伤害\全部伤害事件.csv"
)
DEFAULT_DB = ROOT / "data" / "battle_damage.sqlite"
REFERENCE_FILES = {
    "generals": ROOT / "data" / "generals.json",
    "skills": ROOT / "data" / "skills.json",
    "statuses": ROOT / "data" / "statuses.json",
}

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
    import_id INTEGER PRIMARY KEY,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    battle_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS battles (
    battle_id TEXT PRIMARY KEY,
    source_csv TEXT NOT NULL,
    source_text_path TEXT,
    source_raw_dir TEXT,
    event_count INTEGER NOT NULL DEFAULT 0,
    duplicate_group TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS damage_events (
    event_id INTEGER PRIMARY KEY,
    battle_id TEXT NOT NULL REFERENCES battles(battle_id) ON DELETE CASCADE,
    event_seq INTEGER NOT NULL,
    source_line INTEGER,
    attacker TEXT,
    target TEXT,
    source TEXT,
    skill_name TEXT,
    skill_type TEXT,
    damage_kind TEXT,
    damage_attribute TEXT,
    attacker_troop_type TEXT,
    target_troop_type TEXT,
    attacker_faction TEXT,
    target_faction TEXT,
    attacker_troops REAL,
    attacker_max_troops REAL,
    attacker_troop_ratio REAL,
    target_pre_troops REAL,
    target_post_troops REAL,
    target_max_troops REAL,
    attacker_force REAL,
    attacker_intellect REAL,
    attacker_command REAL,
    attacker_initiative REAL,
    attacker_pierce REAL,
    attacker_insight REAL,
    target_force REAL,
    target_intellect REAL,
    target_command REAL,
    target_initiative REAL,
    observed_damage REAL,
    is_basic_attack INTEGER,
    is_resisted INTEGER,
    resist_multiplier REAL,
    is_critical INTEGER,
    critical_multiplier REAL,
    is_kill_capped INTEGER,
    source_text TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(battle_id, event_seq)
);
CREATE INDEX IF NOT EXISTS idx_damage_attacker ON damage_events(attacker);
CREATE INDEX IF NOT EXISTS idx_damage_target ON damage_events(target);
CREATE INDEX IF NOT EXISTS idx_damage_skill ON damage_events(skill_name, damage_kind);
CREATE INDEX IF NOT EXISTS idx_damage_battle_type ON damage_events(battle_id, damage_kind);
CREATE TABLE IF NOT EXISTS event_snapshots (
    event_id INTEGER NOT NULL REFERENCES damage_events(event_id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK(side IN ('attacker', 'target')),
    general_name TEXT,
    troop_type TEXT,
    current_troops REAL,
    max_troops REAL,
    force REAL,
    intellect REAL,
    command REAL,
    initiative REAL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(event_id, side)
);
CREATE TABLE IF NOT EXISTS event_factors (
    event_id INTEGER NOT NULL REFERENCES damage_events(event_id) ON DELETE CASCADE,
    factor_name TEXT NOT NULL,
    factor_category TEXT NOT NULL,
    numeric_value REAL NOT NULL,
    raw_value TEXT NOT NULL,
    PRIMARY KEY(event_id, factor_name)
);
CREATE INDEX IF NOT EXISTS idx_factors_name_value ON event_factors(factor_name, numeric_value);
CREATE TABLE IF NOT EXISTS data_quality_issues (
    issue_id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES damage_events(event_id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    detail TEXT NOT NULL,
    UNIQUE(event_id, code, detail)
);
CREATE TABLE IF NOT EXISTS reference_generals (
    name TEXT PRIMARY KEY,
    faction TEXT,
    troop_type TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_skills (
    name TEXT PRIMARY KEY,
    owner TEXT,
    skill_type TEXT,
    raw_text TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_statuses (
    name TEXT PRIMARY KEY,
    status_type TEXT,
    raw_text TEXT,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS formula_registry (
    formula_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    equation TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    sample_definition TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK(status IN ('candidate', 'validated', 'superseded', 'rejected')),
    provenance TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

EVENT_FIELD_MAP = {
    "战报": "battle_id",
    "原文行号": "source_line",
    "事件序号": "event_seq",
    "攻击者": "attacker",
    "目标": "target",
    "伤害来源": "source",
    "战法名称": "skill_name",
    "战法类型": "skill_type",
    "伤害类型": "damage_kind",
    "伤害属性": "damage_attribute",
    "攻击者兵种": "attacker_troop_type",
    "目标兵种": "target_troop_type",
    "攻击者阵营": "attacker_faction",
    "目标阵营": "target_faction",
    "攻击者当前兵力": "attacker_troops",
    "攻击者最大兵力": "attacker_max_troops",
    "攻击者兵力比例": "attacker_troop_ratio",
    "目标受击前兵力": "target_pre_troops",
    "目标受击后兵力": "target_post_troops",
    "目标最大兵力": "target_max_troops",
    "攻击者武力": "attacker_force",
    "攻击者智力": "attacker_intellect",
    "攻击者统率": "attacker_command",
    "攻击者先攻": "attacker_initiative",
    "攻击者破甲": "attacker_pierce",
    "攻击者看破": "attacker_insight",
    "目标武力": "target_force",
    "目标智力": "target_intellect",
    "目标统率": "target_command",
    "目标先攻": "target_initiative",
    "实测伤害": "observed_damage",
    "是否普通攻击": "is_basic_attack",
    "是否抵御": "is_resisted",
    "抵御乘区": "resist_multiplier",
    "是否奇谋": "is_critical",
    "奇谋乘区": "critical_multiplier",
    "是否击杀截断": "is_kill_capped",
    "原始文本": "source_text",
}

BOOLEAN_FIELDS = {"是否普通攻击", "是否抵御", "是否奇谋", "是否击杀截断", "攻击者是否识别"}
FACTOR_HINTS = {
    "增伤": "damage_bonus",
    "减伤": "damage_reduction",
    "破甲": "armor_pierce",
    "看破": "insight",
    "兵力": "troops_or_troop_factor",
    "乘区": "multiplier",
    "奇谋": "critical_or_strategy_crit",
    "阵营": "faction_bonus",
    "兵种": "troop_bonus",
    "武力": "attribute",
    "统率": "attribute",
    "智力": "attribute",
    "先攻": "attribute",
}


def _number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _boolean(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "是"}:
        return 1
    if text in {"false", "0", "no", "否"}:
        return 0
    return None


def _json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return {"_raw": value}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _state_value(state: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in state:
            return state[key]
    return None


def _factor_category(name: str) -> str:
    for marker, category in FACTOR_HINTS.items():
        if marker in name:
            return category
    if name in {"攻击者是否识别", "分类依据", "适用攻击加成字段", "适用目标减伤字段", "伤害来源", "伤害类型", "伤害属性", "战法类型", "特殊标记"}:
        return "classification_or_provenance"
    return "other_recorded_factor"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _battle_signature(rows: list[dict[str, str]]) -> str:
    canonical = []
    for row in rows:
        canonical.append({key: value for key, value in row.items() if key != "战报"})
    canonical.sort(key=lambda item: (item.get("事件序号", ""), item.get("原文行号", "")))
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return reader.fieldnames, list(reader)


def _create_reference_rows(conn: sqlite3.Connection, key: str, path: Path) -> None:
    if not path.exists():
        return
    document = json.loads(path.read_text(encoding="utf-8"))
    table, collection_key = {
        "generals": ("reference_generals", "generals"),
        "skills": ("reference_skills", "skills"),
        "statuses": ("reference_statuses", "statuses"),
    }[key]
    records = document.get(collection_key, [])
    if table == "reference_generals":
        conn.execute("DELETE FROM reference_generals")
        conn.executemany(
            "INSERT INTO reference_generals(name, faction, troop_type, raw_json) VALUES(?,?,?,?)",
            [(r.get("name"), r.get("faction"), r.get("troop_type"), json.dumps(r, ensure_ascii=False)) for r in records],
        )
    elif table == "reference_skills":
        conn.execute("DELETE FROM reference_skills")
        conn.executemany(
            "INSERT INTO reference_skills(name, owner, skill_type, raw_text, raw_json) VALUES(?,?,?,?,?)",
            [(r.get("name"), r.get("owner"), r.get("type"), r.get("raw_text"), json.dumps(r, ensure_ascii=False)) for r in records],
        )
    else:
        conn.execute("DELETE FROM reference_statuses")
        flat = []
        for record in records:
            flat.append((record.get("name"), record.get("type"), record.get("raw_text"), json.dumps(record, ensure_ascii=False)))
            for nested in record.get("states", []):
                if isinstance(nested, dict):
                    flat.append((nested.get("name"), nested.get("type", record.get("type")), nested.get("raw_text", record.get("raw_text")), json.dumps(nested, ensure_ascii=False)))
                elif isinstance(nested, str):
                    flat.append((nested, record.get("type"), record.get("raw_text"), json.dumps({"name": nested}, ensure_ascii=False)))
        conn.executemany(
            "INSERT OR REPLACE INTO reference_statuses(name, status_type, raw_text, raw_json) VALUES(?,?,?,?)", flat
        )


def import_data(csv_path: Path, db_path: Path, reference_files: dict[str, Path] | None = None) -> dict[str, int | str]:
    csv_path = csv_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    headers, rows = _read_csv(csv_path)
    if "战报" not in headers or "事件序号" not in headers:
        raise ValueError("CSV must contain 战报 and 事件序号 columns")

    by_battle: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        battle_id = (row.get("战报") or "").strip()
        if battle_id:
            by_battle.setdefault(battle_id, []).append(row)
    signatures: dict[str, list[str]] = {}
    for battle_id, battle_rows in by_battle.items():
        signatures.setdefault(_battle_signature(battle_rows), []).append(battle_id)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        sha = _sha256(csv_path)
        reference_files = REFERENCE_FILES if reference_files is None else reference_files
        with conn:
            conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','1')")
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('troop_type_source_precedence',?)",
                ("标准事件CSV中的攻击者兵种/目标兵种列为校正后的权威值；状态JSON原样保留，仅作来源追溯。",),
            )
            for key, path in reference_files.items():
                _create_reference_rows(conn, key, path)

            for battle_id, battle_rows in by_battle.items():
                duplicate_ids = signatures[_battle_signature(battle_rows)]
                duplicate_group = None
                if len(duplicate_ids) > 1:
                    duplicate_group = "dup-" + _battle_signature(battle_rows)[:16]
                raw_dir = Path(r"D:\battlelog-capture-assistant\captures") / battle_id / "raw"
                text_path = raw_dir / "visible_text.txt"
                conn.execute(
                    """INSERT INTO battles(battle_id,source_csv,source_text_path,source_raw_dir,event_count,duplicate_group,metadata_json)
                       VALUES(?,?,?,?,?,?,?) ON CONFLICT(battle_id) DO UPDATE SET
                       source_csv=excluded.source_csv, source_text_path=excluded.source_text_path,
                       source_raw_dir=excluded.source_raw_dir,event_count=excluded.event_count,
                       duplicate_group=excluded.duplicate_group,metadata_json=excluded.metadata_json""",
                    (battle_id, str(csv_path), str(text_path) if text_path.exists() else None,
                     str(raw_dir) if raw_dir.exists() else None, len(battle_rows), duplicate_group,
                     json.dumps({"duplicate_candidates": duplicate_ids if len(duplicate_ids) > 1 else []}, ensure_ascii=False)),
                )
                conn.execute("DELETE FROM damage_events WHERE battle_id=?", (battle_id,))

                for row in battle_rows:
                    mapped = {db_col: row.get(csv_col) for csv_col, db_col in EVENT_FIELD_MAP.items() if csv_col in row}
                    event_seq = _number(row.get("事件序号"))
                    if event_seq is None:
                        raise ValueError(f"Missing event sequence in battle {battle_id}: {row}")
                    mapped["battle_id"] = battle_id
                    mapped["event_seq"] = int(event_seq)
                    for csv_col, db_col in EVENT_FIELD_MAP.items():
                        if csv_col in BOOLEAN_FIELDS:
                            mapped[db_col] = _boolean(row.get(csv_col))
                        elif db_col not in {"battle_id", "event_seq", "source", "skill_name", "skill_type", "damage_kind", "damage_attribute", "attacker", "target", "attacker_troop_type", "target_troop_type", "attacker_faction", "target_faction", "source_text"}:
                            mapped[db_col] = _number(row.get(csv_col))
                    columns = list(mapped)
                    placeholders = ",".join("?" for _ in columns)
                    cursor = conn.execute(
                        f"INSERT INTO damage_events({','.join(columns)},raw_json) VALUES({placeholders},?)",
                        [mapped[column] for column in columns] + [json.dumps(row, ensure_ascii=False)],
                    )
                    event_id = cursor.lastrowid

                    for side, state_col, prefix, name_col, type_col in (
                        ("attacker", "攻击者状态JSON", "攻击者", "攻击者", "攻击者兵种"),
                        ("target", "目标状态JSON", "目标", "目标", "目标兵种"),
                    ):
                        state = _json(row.get(state_col))
                        conn.execute(
                            """INSERT INTO event_snapshots(event_id,side,general_name,troop_type,current_troops,max_troops,
                               force,intellect,command,initiative,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (event_id, side, row.get(name_col), row.get(type_col) or _state_value(state, "兵种"),
                             _number(_state_value(state, "兵力")) if "兵力" in state else _number(row.get("攻击者当前兵力" if side == "attacker" else "目标受击前兵力")),
                             _number(_state_value(state, "最大兵力")) if "最大兵力" in state else _number(row.get("攻击者最大兵力" if side == "attacker" else "目标最大兵力")),
                             _number(_state_value(state, "武力")) if "武力" in state else _number(row.get("攻击者武力" if side == "attacker" else "目标武力")),
                             _number(_state_value(state, "智力")) if "智力" in state else _number(row.get("攻击者智力" if side == "attacker" else "目标智力")),
                             _number(_state_value(state, "统率")) if "统率" in state else _number(row.get("攻击者统率" if side == "attacker" else "目标统率")),
                             _number(_state_value(state, "先攻")) if "先攻" in state else _number(row.get("攻击者先攻" if side == "attacker" else "目标先攻")),
                             json.dumps(state, ensure_ascii=False)),
                        )

                    for field in headers:
                        value = row.get(field)
                        number = _number(value)
                        if number is not None:
                            conn.execute(
                                "INSERT INTO event_factors(event_id,factor_name,factor_category,numeric_value,raw_value) VALUES(?,?,?,?,?)",
                                (event_id, field, _factor_category(field), number, str(value)),
                            )

                    if _boolean(row.get("攻击者是否识别")) == 0:
                        conn.execute("INSERT OR IGNORE INTO data_quality_issues(event_id,code,detail) VALUES(?,?,?)",
                                     (event_id, "attacker_unrecognized", "采集表标记攻击者未识别；保留原始事件，不建议直接用于归因拟合。"))
                    if _boolean(row.get("是否击杀截断")) == 1:
                        conn.execute("INSERT OR IGNORE INTO data_quality_issues(event_id,code,detail) VALUES(?,?,?)",
                                     (event_id, "kill_capped", "目标兵力归零/击杀截断样本，拟合前应按任务规则筛除。"))
                    if _boolean(row.get("是否抵御")) == 1 or (_number(row.get("抵御乘区")) is not None and _number(row.get("抵御乘区")) < 0.99):
                        conn.execute("INSERT OR IGNORE INTO data_quality_issues(event_id,code,detail) VALUES(?,?,?)",
                                     (event_id, "resisted", "事件受抵御乘区影响，拟合时需显式处理或排除。"))

            conn.execute(
                "INSERT INTO imports(source_path,sha256,imported_at,row_count,battle_count) VALUES(?,?,?,?,?)",
                (str(csv_path), sha, now, len(rows), len(by_battle)),
            )
        return {"database": str(db_path.resolve()), "rows": len(rows), "battles": len(by_battle), "sha256": sha}
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="canonical damage event CSV")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite output file")
    args = parser.parse_args()
    result = import_data(args.csv, args.db)
    print(f"SQLite: {result['database']}")
    print(f"Imported {result['rows']} damage events from {result['battles']} battles")
    print(f"Source SHA-256: {result['sha256']}")


if __name__ == "__main__":
    main()
