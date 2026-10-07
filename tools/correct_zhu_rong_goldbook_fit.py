from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(r"D:\battlelog-capture-assistant")
RAW = BASE / r"captures\20260918_044550_0b0e5dc6\raw\visible_text.txt"
OLD_DAMAGE = BASE / r"csv_output\拟合结果\祝融夫人\南疆烈刃\南疆伤害事件_去重.csv"
OUT = BASE / r"csv_output\拟合结果\祝融夫人\南疆烈刃\金书修正"
OUT.mkdir(parents=True, exist_ok=True)

TAG = re.compile(r"<[^>]*>")
SPACE = re.compile(r"\s+")
ATTRS = ("武力", "统率", "智力", "先攻")


def clean(line: str) -> str:
    return SPACE.sub(" ", TAG.sub("", line)).strip()


def load_lines() -> list[str]:
    raw = [clean(line) for line in RAW.read_text(encoding="utf-8").splitlines()]
    result = []
    for line in raw:
        if line and (not result or line != result[-1]):
            result.append(line)
    return result


def detect_goldbook_status(lines: list[str]) -> pd.DataFrame:
    names = ("张飞", "皇甫嵩", "袁术")
    active = {name: set() for name in names}
    last_down = {name: {} for name in names}
    troop = {}
    events = []

    for index, line in enumerate(lines, 1):
        m = re.search(r"\[([^\]]+)\].*?(?:损失了|恢复了)兵力[\d.]+\(([\d.]+)\)", line)
        if m:
            troop[m.group(1)] = float(m.group(2))

        m = re.search(r"\[([^\]]+)\]的【(武力|统率|智力|先攻)】降低([\d.]+)\(([-\d.]+)\)", line)
        if m and m.group(1) in active:
            name, attr, delta, now = m.groups()
            active[name].add(attr)
            last_down[name][attr] = {"line": index, "delta": float(delta), "now": float(now)}

        m = re.search(r"\[([^\]]+)\]的【(武力|统率|智力|先攻)】提升([\d.]+)\(([-\d.]+)\)", line)
        if m and m.group(1) in active:
            active[m.group(1)].discard(m.group(2))

        m = re.search(r"\[([^\]]+)\]的「南疆烈刃-降」效果已消失", line)
        if m and m.group(1) in active:
            active[m.group(1)].clear()

        m = re.search(r"\[([^\]]+)\]由于\[祝融夫人\].*南疆烈刃.*损失了兵力([\d.]+)\(([\d.]+)\)", line)
        if not m:
            continue
        target, damage, remain = m.groups()
        attrs = sorted(active.get(target, set()))
        recent = {attr: last_down[target][attr]["line"] for attr in attrs if attr in last_down[target]}
        events.append({
            "目标": target,
            "伤害": round(float(damage), 6),
            "目标受击后兵力": round(float(remain), 6),
            "是否属性降低": bool(attrs),
            "属性降低项": ",".join(attrs),
            "属性降低最近行": str(recent),
            "规范化原文序号": index,
            "祝融兵力_重建": troop.get("祝融夫人", np.nan),
        })

    detected = pd.DataFrame(events)
    # Progressive UI snapshots repeat a damage line. Keep the first occurrence
    # of each tuple, matching the old extractor's 24-event table.
    return detected.drop_duplicates(["目标", "伤害", "目标受击后兵力"], keep="first")


def soldier_factor_from_percent(troop: float) -> float:
    x = troop / 11000.0
    if x >= 0.9:
        return 1.0
    if x >= 0.6:
        return 0.063 * x * 10 + 0.433
    if x >= 0.4:
        return 0.073 * x * 10 + 0.373
    if x >= 0.1:
        return 0.8335922058966468 * (1 - np.exp(-0.20422439236668888 * x * 10)) + 0.19638663729131026
    if x >= 0.01:
        return 0.3589214157800344 * (1 - np.exp(-1.0509781686228445 * x * 10)) + 0.11249477230478798
    return 0.10332192473573393 * (1 - np.exp(-11.27882258789204 * x * 10)) + 0.07203069815884945


def fit_models(x: np.ndarray, y: np.ndarray) -> pd.DataFrame:
    valid = np.isfinite(x) & np.isfinite(y)
    x = x[valid]
    y = y[valid]
    models = {
        "linear": (lambda x, a, b: a + b * x, [1.0, 2.0]),
        "power": (lambda x, a, p: 1 + a * x**p, [2.0, 1.0]),
        "exp": (lambda x, a, p: np.exp(a * x**p), [2.0, 1.0]),
        "power_free": (lambda x, a, b, p: a + b * x**p, [1.0, 1.0, 1.0]),
    }
    rows = []
    for name, (func, p0) in models.items():
        popt, _ = curve_fit(func, x, y, p0=p0, maxfev=500000)
        pred = func(x, *popt)
        ss_res = np.sum((y - pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        rows.append({
            "模型": name,
            "参数": str([round(float(v), 8) for v in popt]),
            "R2": 1 - ss_res / ss_tot if ss_tot else np.nan,
            "RMSE": float(np.sqrt(np.mean((y - pred) ** 2))),
            "平均绝对相对误差_%": float(np.mean(np.abs((y - pred) / np.maximum(np.abs(y), 1e-9))) * 100),
        })
    return pd.DataFrame(rows).sort_values("RMSE").reset_index(drop=True)


def main() -> None:
    old = pd.read_csv(OLD_DAMAGE, encoding="utf-8-sig")
    status = detect_goldbook_status(load_lines())
    keys = ["目标", "伤害", "目标受击后兵力"]
    for col in keys:
        old[col] = pd.to_numeric(old[col], errors="coerce") if col != "目标" else old[col]
        status[col] = pd.to_numeric(status[col], errors="coerce") if col != "目标" else status[col]
    old = old.merge(status, on=keys, how="left")
    if old["是否属性降低"].isna().any():
        missing = old[old["是否属性降低"].isna()][keys]
        raise RuntimeError(f"未能绑定金书状态的样本:\n{missing.to_string(index=False)}")

    old["祝融兵力"] = old["祝融兵力"].fillna(old["祝融兵力_重建"])
    old["金书乘区"] = np.where(old["是否属性降低"], 1.06, 1.00)
    old["兵力差比例"] = (old["目标受击前兵力"] - old["祝融兵力"]).abs() / 11000.0
    old["兵力系数"] = old["祝融兵力"].apply(soldier_factor_from_percent)

    # These are the same confirmed critical-hit events used by the previous
    # PVP analysis. A critical hit is one 1.5 multiplier for that damage line.
    crit_rows = {2091, 2131, 2173, 4737, 4795, 4813, 6523, 6541, 6559,
                 7795, 7825, 7843, 10211, 10239, 10257}
    old["奇谋/会心乘区"] = np.where(old["原文行号"].isin(crit_rows), 1.5, 1.0)

    # Existing PVP baseline used for this specific Zhurong troop-difference fit.
    K = 692.1484366616
    old["基础伤害"] = K * (old["祝融武力"] + 500) / (old["目标统率"] + 1200) - 129.7980360507
    target_reduce = 1 - old["目标受到伤害降低"] / 100.0
    faction = old["目标"].map({
        "张飞": 1.04 * 0.95,
        "皇甫嵩": 1.04 * 0.95,
        "袁术": 1.01 * 0.95,
    }).fillna(1.0)
    known = (
        old["基础伤害"] * 0.927 * old["兵力系数"] * 1.13
        * (0.1 + 0.9 * (1 + 0.26) * target_reduce)
        * (1 - old["目标受到兵刃伤害降低"].fillna(0) / 100.0)
        * faction * old["奇谋/会心乘区"]
    )

    # Compare the old universal 1.05 assumption with the actual conditional
    # gold-book rule. The old value is retained for an exact before/after audit.
    old["F_旧_统一1.05"] = old["伤害"] / (known * 1.05)
    old["F_旧_统一1.06"] = old["伤害"] / (known * 1.06)
    old["F_修正_条件1.06"] = old["伤害"] / (known * old["金书乘区"])
    old["修正相对旧值_%"] = (old["F_修正_条件1.06"] / old["F_旧_统一1.05"] - 1) * 100

    finite = np.isfinite(old[["兵力差比例", "F_旧_统一1.05", "F_旧_统一1.06", "F_修正_条件1.06"]]).all(axis=1)
    print(f"拟合有效样本: {int(finite.sum())}/{len(old)}")
    if (~finite).any():
        print("非有限样本（保留在逐条表，不参加拟合）：")
        print(old.loc[~finite, ["原文行号", "目标", "伤害", "祝融兵力", "目标统率", "目标受到伤害降低", "金书乘区"]].to_string(index=False))

    fit_rows = []
    for label, column in (("旧_统一1.05", "F_旧_统一1.05"), ("旧_统一1.06", "F_旧_统一1.06"), ("修正_条件1.06", "F_修正_条件1.06")):
        result = fit_models(old.loc[finite, "兵力差比例"].to_numpy(), old.loc[finite, column].to_numpy())
        result.insert(0, "版本", label)
        fit_rows.append(result)
    fits = pd.concat(fit_rows, ignore_index=True)

    old.to_csv(OUT / "南疆伤害_金书修正后逐条.csv", index=False, encoding="utf-8-sig")
    fits.to_csv(OUT / "金书修正前后模型对比.csv", index=False, encoding="utf-8-sig")

    summary = [
        "# 祝融夫人金书 6% 对南疆兵力差拟合的修正",
        "",
        "规则：目标在伤害发生时存在武力/统率/智力/先攻任一属性降低，金书乘区=1.06；否则=1.00。",
        "旧脚本对照：分别列出所有样本统一使用 1.05、统一使用 1.06，以及正确的条件乘区。",
        "",
        f"样本数：{len(old)}",
        f"识别为属性降低：{int(old['是否属性降低'].sum())}",
        f"未识别为属性降低：{int((~old['是否属性降低']).sum())}",
        "",
        "逐条修正相对旧统一1.05的变化：",
        f"  触发金书：{(old.loc[old['金书乘区'] > 1, '修正相对旧值_%']).mean():.3f}%（理论为 -0.943%）",
        f"  未触发金书：{(old.loc[old['金书乘区'] == 1, '修正相对旧值_%']).mean():.3f}%（理论为 +5.000%）",
        "",
        "模型对比见：金书修正前后模型对比.csv",
        "逐条核对见：南疆伤害_金书修正后逐条.csv",
    ]
    (OUT / "金书修正说明.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    print("=== 金书状态统计 ===")
    print(old[["原文行号", "目标", "伤害", "是否属性降低", "属性降低项", "金书乘区"]].to_string(index=False))
    print("\n=== 前后拟合对比 ===")
    print(fits.to_string(index=False))
    print(f"\n输出目录: {OUT}")


if __name__ == "__main__":
    main()
