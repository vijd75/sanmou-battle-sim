from __future__ import annotations

import csv
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = Path(r"D:\battlelog-capture-assistant\captures\20260925_011224_5b9bb088")
EXTRACTOR = Path(r"D:\battlelog-capture-assistant\csv_output\脚本\extract_all_damage_events.py")
sys.path.insert(0, str(EXTRACTOR.parents[2]))
import extract_damage_events as base  # noqa: E402

spec = importlib.util.spec_from_file_location("extract_all_damage_events", EXTRACTOR)
extractor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = extractor
spec.loader.exec_module(extractor)

visible = CAPTURE / "raw" / "visible_text.txt"
raw_lines = visible.read_text(encoding="utf-8", errors="replace").splitlines()
cleaned, raw_line_numbers = [], []
previous = None
for raw_no, raw in enumerate(raw_lines, 1):
    line = base.clean_line(raw)
    if not line or line == "---" or base.PLACEHOLDER_RE.search(line) or line == previous:
        continue
    cleaned.append(line)
    raw_line_numbers.append(raw_no)
    previous = line
assert cleaned == base.load_clean_lines(visible)

text_rows = [r for r in extractor.extract_file(visible)
             if r["战法名称"] == "九伐中原" and "讨伐" in r["伤害来源"]]
old_rows = list(csv.DictReader((ROOT / "reports" / "2026-09-25-镜像姜维九伐逐击数据.csv").open(encoding="utf-8-sig")))
assert len(text_rows) == len(old_rows) == 26
assert [r["实测伤害"] for r in text_rows] == [int(r["实测伤害"]) for r in old_rows]

# Replay the exact parser state in order, retaining physical lines that supplied
# the latest cumulative property snapshots.
static = base.infer_static_info(cleaned)
states = {n: {**s, **({"兵力": s["最大兵力"]} if "最大兵力" in s else {})}
          for n, s in static.items()}
provenance, row_provenance = {}, {}
selected_at = {r["原文行号"]: i for i, r in enumerate(text_rows)}
for clean_no, line in enumerate(cleaned, 1):
    before = {name: dict(value) for name, value in states.items()}
    base.update_state(line, states)
    for name, state in states.items():
        for key, value in state.items():
            if before.get(name, {}).get(key) != value:
                provenance[(name, key)] = (raw_line_numbers[clean_no - 1], line)
    if clean_no in selected_at:
        i = selected_at[clean_no]
        row = text_rows[i]
        row_provenance[i] = {
            (row["攻击者"], key): provenance.get((row["攻击者"], key))
            for key in ("增伤", "兵刃增伤", "谋略增伤", "武力", "智力", "破甲")
        } | {
            (row["目标"], key): provenance.get((row["目标"], key))
            for key in ("净减伤", "兵刃净减伤", "谋略净减伤", "统率", "智力")
        }
    

timeline = [json.loads(line) for line in (CAPTURE / "decoded" / "timeline.jsonl").read_text(encoding="utf-8").splitlines()]
timeline_by_index = {e["event_index"]: e for e in timeline}
no_weapon_text = "受到兵刃伤害" not in visible.read_text(encoding="utf-8", errors="replace")
assert no_weapon_text
zero_evidence = (f"visible_text.txt 全文（物理行1-{len(raw_lines)}）；检索‘受到兵刃伤害’"
                 "及‘降低/提升/效果已施加/效果已消失’，无生效状态行；故该累计字段记0%。")

rows, pred_rows = [], []
for i, (old, text) in enumerate(zip(old_rows, text_rows)):
    event_index = int(old["事件序号"])
    ev = timeline_by_index[event_index]
    args = ev["args"]
    assert args["changeSoldierNum"] == text["实测伤害"]
    attacker, target = text["攻击者"], text["目标"]
    atk_state = json.loads(text["攻击者状态JSON"])
    target_state = json.loads(text["目标状态JSON"])
    def evidence(person: str, state_key: str, val: float) -> str:
        source = row_provenance[i].get((person, state_key))
        if source:
            line_no, statement = source
            return f"visible_text.txt:L{line_no} 累计状态原文：{statement}"
        if val == 0 and state_key == "兵刃净减伤":
            return zero_evidence
        raise ValueError(f"missing state evidence {event_index} {person} {state_key}={val}")
    def state_evidence(person: str, state_key: str) -> str:
        if state_key == "兵力":
            if person == attacker:
                team_id, hero_id = args["srcTeamId"], args["damageSourceHeroId"]
            else:
                team_id, hero_id = args["teamId"], args["targetHeroId"]
            token = f"{team_id}_{hero_id}"
            limit = raw_line_numbers[text["原文行号"] - 1]
            changes = []
            for physical, raw in enumerate(raw_lines[:limit - 1], 1):
                change = base.TROOP_CHANGE_RE.search(base.clean_line(raw))
                if change and change.group("name") == person and token in raw:
                    changes.append((physical, base.clean_line(raw)))
            if changes:
                physical, statement = changes[-1]
                return f"visible_text.txt:L{physical} 兵力前态来源：{statement}"
            raise ValueError(f"missing troop state evidence {event_index} {person} {token}")
        source = row_provenance[i].get((person, state_key))
        if not source:
            raise ValueError(f"missing state evidence {event_index} {person} {state_key}")
        line_no, statement = source
        return f"visible_text.txt:L{line_no}: {statement}"

    common_up = float(text["攻击者增伤"])
    weapon_up = float(text["攻击者兵刃增伤"])
    strategy_up = float(text["攻击者谋略增伤"])
    common_down = float(text["目标净减伤"])
    weapon_down = float(text["目标兵刃净减伤"])
    strategy_down = float(text["目标谋略净减伤"])
    evidence_values = [
        evidence(attacker, "增伤", common_up), evidence(attacker, "兵刃增伤", weapon_up),
        evidence(attacker, "谋略增伤", strategy_up), evidence(target, "净减伤", common_down),
        evidence(target, "兵刃净减伤", weapon_down), evidence(target, "谋略净减伤", strategy_down),
    ]

    # Attacker's latest propertyId=174 snapshot in this round, before this strike.
    a_team, a_id = args["srcTeamId"], args["damageSourceHeroId"]
    prior = [e for e in timeline if e["event_index"] < event_index and e.get("round") == ev.get("round")
             and (e.get("args") or {}).get("teamId") == a_team
             and (e.get("args") or {}).get("heroId") == a_id
             and (e.get("args") or {}).get("propertyId") == 174]
    prop = max(prior, key=lambda e: e["event_index"])
    stacks = int(prop["args"]["resultPropertyValue"] / 10000)
    skill_rate = 40 + 5 * stacks
    insight_events = [e for e in timeline if e["event_index"] < event_index
                      and e.get("round") == ev.get("round")
                      and (e.get("args") or {}).get("teamId") == a_team
                      and (e.get("args") or {}).get("heroId") == a_id
                      and (e.get("args") or {}).get("propertyId") == 49]
    insight_event = max(insight_events, key=lambda e: e["event_index"])
    insight_pct = float(insight_event["args"]["resultPropertyValue"]) / 100
    look_lines = [(n, base.clean_line(line)) for n, line in enumerate(raw_lines[:raw_line_numbers[text["原文行号"] - 1]], 1)
                  if f"{a_team}_{a_id}" in line and "看破" in line]
    matching_look_lines = [(n, line) for n, line in look_lines
                           if re.search(rf"看破.*?\((-?{insight_pct:.2f})%\)", line)]
    if not matching_look_lines:
        # The tag parser may put text between label and parenthesized value.
        matching_look_lines = [(n, line) for n, line in look_lines
                               if re.search(rf"\((-?{insight_pct:.2f})%\)", line)]
    if not matching_look_lines:
        raise ValueError(f"no raw visible-text evidence for propertyId=49 before event {event_index}: {insight_pct}%")
    insight_evidence_line, insight_evidence_text = matching_look_lines[-1]

    # Current simulation's troop curve, with user-confirmed 11000 maximum.
    troop_ratio = float(text["攻击者当前兵力"]) / 11000
    x = troop_ratio * 10
    if x >= 9: troop_factor = 1.0
    elif x >= 6: troop_factor = .063 * x + .433
    elif x >= 4: troop_factor = .073 * x + .373
    elif x >= 1: troop_factor = .8335922058966468 * (1 - math.exp(-.20422439236668888 * x)) + .19638663729131026
    elif x >= .1: troop_factor = .3589214157800344 * (1 - math.exp(-1.0509781686228445 * x)) + .11249477230478798
    else: troop_factor = .10332192473573393 * (1 - math.exp(-11.27882258789204 * x)) + .07203069815884945

    force, intellect = float(text["攻击者武力"]), float(text["攻击者智力"])
    command, target_i = float(text["目标统率"]), float(text["目标智力"])
    pierce = float(text["攻击者破甲"])
    insight = insight_pct / 100
    effective_command = max(0, command * (1 - .858227 * pierce / 100))
    effective_target_i = max(0, target_i * (1 - .436802 * insight))
    scaled = (force - 350.0) / 42.229892
    softplus = scaled if scaled > 40 else math.log1p(math.exp(scaled))
    base_weapon = (181.246541 * (force + 177.097104) + 633.945615 * 42.229892 * softplus) / (effective_command + 76.751897) + 34.118963
    def strategy_base(effective_command_value: float) -> float:
        value = 422.88527020 + .62709505 * intellect - .30029221 * effective_target_i - .54813767 * effective_command_value
        for bp, a, b, c in ((120.,1.46788045,-.00266870,-.00173418),(200.,-1.20322956,.00197171,.00256683),(500.,.60127771,.00643166,-.00430132),(540.,1.53798160,-.00248899,-.00014062),(620.,9.20652279,-.02263491,-.00314806)):
            value += max(intellect - bp, 0) * (a + b * effective_target_i + c * effective_command_value)
        return value
    dtype = old["伤害类型"]
    if dtype == "兵刃":
        base_candidate = base_weapon
        effective_command_code = max(0, command - 5.285313 * pierce)
        base_code = (181.246541 * (force + 177.097104) + 633.945615 * 42.229892 * softplus) / (effective_command_code + 76.751897) + 34.118963
        type_up, type_down = weapon_up, weapon_down
    else:
        # Piercing is the weapon-side defense adjustment; strategy damage uses
        # insight against target intellect and leaves command unchanged.
        base_candidate = strategy_base(command)
        base_code = strategy_base(command)
        type_up, type_down = strategy_up, strategy_down

    dealt_pool = min(100, max(0, common_up) + max(0, type_up))
    timing_up = float(text["攻击者指挥战法增伤"])
    timing_down = max(0, float(text["目标指挥战法净减伤"]))
    dealt_multiplier = (1 + dealt_pool / 100) * (1 + timing_up / 100)
    taken_multiplier = (1 - common_down / 100) * (1 - max(0, type_down) / 100) * (1 - timing_down / 100)
    front_multiplier = 1.2 if target != "姜维" else 1.0
    # The extractor's hard-coded general-to-troop map conflicts with this
    # battle's explicit troop-status events. Use the original battlefield type.
    attacker_troop = atk_state.get("兵种", "")
    target_troop = target_state.get("兵种", "")
    assert attacker_troop == target_troop == "盾兵"
    troop_multiplier = 1.0
    faction_multiplier = .988  # prior project rules: Shu attacker vs Wei/Shu target, 1.04 * 0.95
    crit_multiplier = 1.0
    measured = int(old["实测伤害"])
    candidate = int(base_candidate * (skill_rate/100) * troop_factor * troop_multiplier * faction_multiplier * front_multiplier * dealt_multiplier * taken_multiplier * crit_multiplier)
    code_pred = int(base_code * (skill_rate/100) * troop_factor * troop_multiplier * faction_multiplier * front_multiplier * dealt_multiplier * taken_multiplier * crit_multiplier)

    evidence_cols = ["证据_攻击者通用造成伤害","证据_攻击者造成兵刃伤害","证据_攻击者造成谋略伤害","证据_目标通用受到伤害","证据_目标受到兵刃伤害降低","证据_目标受到谋略伤害降低"]
    hit_raw_line = raw_line_numbers[text["原文行号"] - 1]
    def troop_evidence(team_id: int, hero_id: int) -> str:
        token = f"{team_id}_{hero_id}"
        prior_rows = [(n, line) for n, line in enumerate(raw_lines[:hit_raw_line], 1)
                      if token in line and "兵种加成-盾兵" in line]
        if not prior_rows:
            raise ValueError(f"missing battlefield troop evidence {event_index} {token}")
        n, line = prior_rows[-1]
        return f"visible_text.txt:L{n} {line.strip()}"
    attacker_troop_evidence = troop_evidence(args["srcTeamId"], args["damageSourceHeroId"])
    target_troop_evidence = troop_evidence(args["teamId"], args["targetHeroId"])
    row = {
        "session_id": CAPTURE.name, "stream_id": ev["stream_id"], "event_index": event_index,
        "round": ev.get("round"), "event_id": ev["event_id"], "event_name": ev["event_name"],
        "原文行号": hit_raw_line,
        "清洗原文行号": text["原文行号"], "伤害来源": text["伤害来源"], "伤害类型": dtype,
        "攻击者": attacker, "目标": target, "目标站位": "后排" if target == "姜维" else "前排",
        "攻击者当前兵力": text["攻击者当前兵力"], "攻击者最大兵力": 11000,
        "攻击者兵力比例": troop_ratio, "兵力系数": troop_factor, "目标受击前兵力": text["目标受击前兵力"],
        "攻击者武力": force, "攻击者智力": intellect, "目标统率": command, "目标智力": target_i,
        "证据_攻击者武力":state_evidence(attacker,"武力"), "证据_攻击者智力":state_evidence(attacker,"智力"),
        "证据_目标统率":state_evidence(target,"统率"), "证据_目标智力":state_evidence(target,"智力"),
        "攻击者兵力状态证据":state_evidence(attacker,"兵力"), "目标兵力状态证据":state_evidence(target,"兵力"),
        "攻击者破甲_pct": pierce, "证据_攻击者破甲":state_evidence(attacker,"破甲"),
        "攻击者看破_pct": insight_pct,
        "看破状态事件序号": insight_event["event_index"],
        "证据_攻击者看破": f"timeline event#{insight_event['event_index']} propertyId=49; visible_text.txt:L{insight_evidence_line}: {insight_evidence_text}",
        "九伐有效层数": stacks, "九伐系数_pct": skill_rate,
        "攻击者通用造成伤害_pct": common_up, "证据_攻击者通用造成伤害": evidence_values[0],
        "攻击者造成兵刃伤害_pct": weapon_up, "证据_攻击者造成兵刃伤害": evidence_values[1],
        "攻击者造成谋略伤害_pct": strategy_up, "证据_攻击者造成谋略伤害": evidence_values[2],
        "目标通用受到伤害降低_pct": common_down, "证据_目标通用受到伤害": evidence_values[3],
        "目标通用受到伤害原始净值_pct": -common_down,
        "目标受到兵刃伤害降低_pct": weapon_down, "证据_目标受到兵刃伤害降低": evidence_values[4],
        "目标受到兵刃伤害原始净值_pct": -weapon_down,
        "目标受到谋略伤害降低_pct": strategy_down, "证据_目标受到谋略伤害降低": evidence_values[5],
        "目标受到谋略伤害原始净值_pct": -strategy_down,
        "攻击者指挥战法增伤_pct": text["攻击者指挥战法增伤"], "目标受到指挥战法伤害降低_pct": text["目标指挥战法净减伤"],
        "攻击者战场兵种": attacker_troop, "证据_攻击者战场兵种": attacker_troop_evidence,
        "目标战场兵种": target_troop, "证据_目标战场兵种": target_troop_evidence,
        "兵种关系": f"{attacker_troop}→{target_troop}", "兵种乘区": troop_multiplier, "阵营乘区": faction_multiplier,
        "目标前排乘区": front_multiplier, "是否抵御": text["是否抵御"], "是否奇谋": text["是否奇谋"],
        "会心/奇谋乘区": crit_multiplier, "是否击杀截断": text["是否击杀截断"],
        "实测伤害": measured,
        "基础伤害_百分比破甲候选": base_candidate,"预测伤害_百分比破甲候选": candidate,
        "预测误差_候选": candidate-measured,"基础伤害_当前固定点代码":base_code,
        "预测伤害_当前固定点代码":code_pred,"预测误差_当前固定点代码":code_pred-measured,
        "property174证据事件序号":prop["event_index"],"property174当前值":prop["args"]["resultPropertyValue"],
        "纳入说明":"纳入：26条讨伐直接伤害；逐项状态证据齐全；类型按兵刃先、谋略后时序映射。"
    }
    rows.append(row)

    pred_rows.append({"event_index":event_index,"round":ev.get("round"),"target":target,"damage_type":dtype,
        "skill_rate_pct":skill_rate,"measured":measured,"predicted_percent_pierce_candidate":candidate,
        "residual_candidate":candidate-measured,"predicted_code_fixed_point":code_pred,
        "residual_code_fixed_point":code_pred-measured})

out_audit = ROOT / "reports" / "2026-09-25-镜像姜维九伐逐击核账.csv"
with out_audit.open("w", encoding="utf-8-sig", newline="") as f:
    w=csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
pred_file=ROOT / "reports" / "2026-09-25-镜像姜维九伐固定公式回代.csv"
with pred_file.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(pred_rows[0]));w.writeheader();w.writerows(pred_rows)

def metrics(data, pred):
    ys=[int(r["实测伤害"]) for r in data]; ps=[int(r[pred]) for r in data]
    mean=sum(ys)/len(ys)
    return {"n":len(ys),"R2":1-sum((p-y)**2 for y,p in zip(ys,ps))/sum((y-mean)**2 for y in ys),
        "RMSE":math.sqrt(sum((p-y)**2 for y,p in zip(ys,ps))/len(ys)),
        "MAE":sum(abs(p-y) for y,p in zip(ys,ps))/len(ys),
        "MAPE_pct":sum(abs(p-y)/y for y,p in zip(ys,ps))/len(ys)*100,
        "mean_signed_error":sum(p-y for y,p in zip(ys,ps))/len(ys)}

metric_rows=[]
for version,pred in (("百分比破甲候选","预测伤害_百分比破甲候选"),("当前固定点代码","预测伤害_当前固定点代码")):
    for group in ("总体","兵刃","谋略"):
        subset=rows if group=="总体" else [r for r in rows if r["伤害类型"]==group]
        metric_rows.append({"模型版本":version,"分组":group,**metrics(subset,pred)})
metric_file=ROOT/"reports"/"2026-09-25-镜像姜维九伐回代指标.csv"
with metric_file.open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(metric_rows[0]));w.writeheader();w.writerows(metric_rows)
print("audit rows",len(rows),"raw lines",len(raw_lines))
for r in metric_rows: print(r)
print(out_audit);print(pred_file);print(metric_file)
