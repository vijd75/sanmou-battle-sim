import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).parent
extractor_path = Path(r"D:\battlelog-capture-assistant\csv_output\脚本\extract_all_damage_events.py")
spec = importlib.util.spec_from_file_location("capture_damage_extractor", extractor_path)
extractor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = extractor
spec.loader.exec_module(extractor)
capture = Path(r"D:\battlelog-capture-assistant\captures\20260925_045709_5e4deef5\raw\visible_text.txt")
rows = extractor.extract_file(capture)

def soldiers_factor(current, maximum):
    x = 10 * current / maximum
    if x >= 9:
        return 1.0
    if x >= 6:
        return 0.063 * x + 0.433
    if x >= 4:
        return 0.073 * x + 0.373
    if x >= 1:
        return 0.8335922058966468 * (1 - math.exp(-0.20422439236668888 * x)) + 0.19638663729131026
    if x >= 0.1:
        return 0.3589214157800344 * (1 - math.exp(-1.0509781686228445 * x)) + 0.11249477230478798
    return 0.10332192473573393 * (1 - math.exp(-11.27882258789204 * x)) + 0.07203069815884945

def strategy_base(ai, ti, tc):
    value = 422.88527020 + 0.62709505 * ai - 0.30029221 * ti - 0.54813767 * tc
    for bp, a, b, c in (
        (120.0, 1.46788045, -0.00266870, -0.00173418),
        (200.0, -1.20322956, 0.00197171, 0.00256683),
        (500.0, 0.60127771, 0.00643166, -0.00430132),
        (540.0, 1.53798160, -0.00248899, -0.00014062),
        (620.0, 9.20652279, -0.02263491, -0.00314806),
    ):
        excess = max(ai - bp, 0.0)
        value += excess * (a + b * ti + c * tc)
    return value

sequence = {
    29: "兵刃", 30: "谋略", 31: "兵刃", 32: "谋略", 33: "兵刃", 34: "谋略", 35: "兵刃", 36: "谋略",
    66: "兵刃", 67: "兵刃", 68: "兵刃", 69: "谋略", 72: "兵刃", 73: "谋略", 74: "兵刃",
}
out = []
for row in rows:
    try:
        event = int(row["事件序号"])
    except (KeyError, ValueError, TypeError):
        continue
    if event not in sequence or "九伐中原-讨伐" not in str(row.get("伤害来源", "")):
        continue
    kind = sequence[event]
    current = 8386 if event <= 36 else 894
    maximum = 8386
    troop_factor = soldiers_factor(current, maximum)
    force, intellect = float(row["攻击者武力"]), float(row["攻击者智力"])
    command, target_intellect = float(row["目标统率"]), float(row["目标智力"])
    pierce = float(row["攻击者破甲"]) / 100
    if kind == "兵刃":
        effective_command = max(0.0, command * (1 - 0.858227 * pierce))
        scaled = (force - 350.0) / 42.229892
        softplus = scaled if scaled > 40 else math.log1p(math.exp(scaled))
        base = (181.246541 * (force + 177.097104) + 633.945615 * 42.229892 * softplus) / (effective_command + 76.751897) + 34.118963
    else:
        base = strategy_base(intellect, max(0.0, target_intellect), command)
    type_bonus = float(row["攻击者兵刃增伤"] if kind == "兵刃" else row["攻击者谋略增伤"]) / 100
    dealt = 1 + float(row["攻击者增伤"]) / 100 + type_bonus
    type_reduction = float(row["目标兵刃净减伤"] if kind == "兵刃" else row["目标谋略净减伤"]) / 100
    taken = (1 - float(row["目标净减伤"]) / 100) * (1 - type_reduction)
    front = 1.20 if row["目标"] in ("马腾", "钟会") else 1.0
    matchup = 1.13 if row["目标"] in ("马腾", "公孙瓒") else 1.0
    damage_no_skill_rate = base * dealt * taken * troop_factor * front * matchup
    actual = int(row["实测伤害"])
    resist = float(row.get("抵御乘区") or 1)
    kill = bool(row.get("是否击杀截断"))
    exclusions = []
    if resist < 0.999:
        exclusions.append("抵御样本，未用于类型系数拟合")
    if kill:
        exclusions.append("击杀截断")
    out.append({
        "session_id": "20260925_045709_5e4deef5", "event_order": event,
        "round": 1 if event <= 36 else 2, "attacker": "姜维", "target": row["目标"],
        "damage_type": kind, "actual_damage": actual, "attacker_current_troops_used": current,
        "inferred_max_troops": maximum, "soldiers_factor": round(troop_factor, 8),
        "force": force, "intellect": intellect, "target_command": command,
        "target_intellect": target_intellect, "armor_pierce_pct": float(row["攻击者破甲"]),
        "attacker_general_damage_bonus_pct": float(row["攻击者增伤"]),
        "attacker_type_damage_modifier_pct": float(type_bonus * 100),
        "target_general_reduction_pct": float(row["目标净减伤"]),
        "target_type_reduction_pct": float(row["目标兵刃净减伤"] if kind == "兵刃" else row["目标谋略净减伤"]),
        "target_pre_hit_troops": row["目标受击前兵力"], "target_post_hit_troops": row["目标受击后兵力"],
        "front_multiplier_assumed": front, "counter_multiplier_assumed": matchup,
        "resist_multiplier": resist, "kill_clamped": kill,
        "implied_skill_coefficient_pct": round(100 * actual / damage_no_skill_rate, 2),
        "include_in_type_fit": "no" if exclusions else "yes",
        "exclusion_reason": "; ".join(exclusions),
    })

if out:
    with (BASE / "2026-09-25-新包九伐逐击反推.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)

first_by_target = {}
for row in rows:
    target = row.get("目标")
    if not target or row.get("目标受击后兵力") is None:
        continue
    try:
        event = int(row["事件序号"])
    except (KeyError, ValueError, TypeError):
        continue
    if target not in first_by_target or event < first_by_target[target][0]:
        first_by_target[target] = (event, row)
with (BASE / "2026-09-25-新包首次受击与最大兵力.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    fields = ["general", "first_captured_damage_order", "first_captured_damage_source", "damage", "troops_after", "reconstructed_troops_before", "maximum_troops_observed_in_capture", "inference"]
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    for target, (event, row) in sorted(first_by_target.items(), key=lambda item: item[1][0]):
        after = int(row["目标受击后兵力"])
        damage = int(row["实测伤害"])
        before = int(row["目标受击前兵力"])
        maximum = int(row["目标最大兵力"] or 0)
        if before == maximum:
            inference = "首次记录受击前兵力等于本战最大观测兵力；在此前无漏记受击前提下可反推最大兵力"
        else:
            inference = "首条可解析受击时已低于本战最大观测兵力；单凭该击只能恢复当前兵力，不能把它当最大兵力"
        writer.writerow({"general": target, "first_captured_damage_order": event, "first_captured_damage_source": row.get("伤害来源"), "damage": damage, "troops_after": after, "reconstructed_troops_before": before, "maximum_troops_observed_in_capture": maximum, "inference": inference})

escapes = [
    ("20260924_042022_eb9823e3", 460.93, 550.85, 2010, 2803, "祝融夫人", 1.0, 12.55, "text-only; attacker extra +8.5% appears in log"),
    ("20260924_172329_73d9111f", 482.5219, 657.3132, 1434, 3929, "刘禅", .7, 8.34, "explicit attacker weakRatio 70"),
    ("20260924_172329_73d9111f", 555.2815, 640.1903, 1556, 1599, "刘禅", .7, 7.34, "explicit attacker weakRatio 70"),
    ("20260924_234108_4e3b9d8f", 575.52, 687.23, 2959, 4082, "邓艾", 1.0, 29.71, "generic modifiers not normalized"),
    ("20260925_011224_5b9bb088", 480.0005, 627.4508, 2362, 4964, "诸葛亮", 1.0, 43.46, "uncensored; target also shows strategy-specific reduction 20.85%, escape applicability unknown"),
    ("20260925_045709_5e4deef5", 474.07, 591.19, 2212, 2326, "马腾", 1.0, 7.49, "uncensored; decode failed, parsed visible text"),
]
with (BASE / "2026-09-25-九伐逃兵拟合样本.csv").open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(["session_id", "force", "intellect", "observed_escape", "target_troops_before", "target", "attacker_weak_ratio_multiplier", "target_general_damage_reduction_pct_metadata_only_escape_ignores_it", "counterfactual_only_dividing_by_target_reduction_do_not_use", "status_note", "old_2.4_sum_minus_631"])
    for session, force, intellect, damage, troops, target, weak, target_reduction, note in escapes:
        writer.writerow([session, force, intellect, damage, troops, target, weak, target_reduction, damage / (weak * (1 - target_reduction / 100)), note, 2.4 * (force + intellect) - 631])
print(f"direct rows={len(out)}; escape rows={len(escapes)}")
