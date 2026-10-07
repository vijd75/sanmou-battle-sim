"""Fit Huangfu Song's 兵动若神 command-difference multiplier.

The 20260918_044550 report is excluded because its three hits occur after an
unexplained 66.1% damage-dealt reduction, consistent with the Zhou Yu
协防/迟滞 chain.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit


INPUT = Path(r"D:\battlelog-capture-assistant\csv_output\拟合结果\兵力系数\全部伤害\整体拟合\整体拟合逐条误差.csv")
OUT_DIR = Path("data/analysis/huangfu_command_difference")
EXCLUDED_REPORT = "20260918_044550_0b0e5dc6"
SKILL_RATE = 2.60


def col(frame: pd.DataFrame, name: str) -> str:
    if name not in frame.columns:
        raise KeyError(f"missing column: {name}")
    return name


def base_weapon(force: np.ndarray, command: np.ndarray) -> np.ndarray:
    return 1186.41 * (force + 500.0) / (command + 1200.0) - 301.58


def fit_and_score(func, x, y, p0, bounds=(-np.inf, np.inf)):
    params, _ = curve_fit(func, x, y, p0=p0, bounds=bounds, maxfev=200000)
    pred = func(x, *params)
    residual = y - pred
    ss_tot = np.sum((y - y.mean()) ** 2)
    return params, pred, 1 - np.sum(residual**2) / ss_tot, np.sqrt(np.mean(residual**2))


def main() -> None:
    frame = pd.read_csv(INPUT, encoding="utf-8-sig")
    frame = frame[frame[col(frame, "战法名称")] == "兵动若神"].copy()
    frame = frame[frame[col(frame, "是否抵御")].astype(str).str.lower() != "true"].copy()
    frame = frame[frame[col(frame, "抵御乘区")].astype(float) >= 0.999].copy()
    frame = frame[frame[col(frame, "战报")] != EXCLUDED_REPORT].copy()

    numeric = [
        "攻击者武力", "攻击者统率", "目标统率", "攻击者当前兵力",
        "目标武力", "目标受击前兵力", "目标最大兵力",
        "攻击者增伤", "攻击者兵刃增伤", "目标净减伤", "目标兵刃净减伤",
        "兵种乘区", "阵营乘区", "兵力系数_最佳alpha", "实测伤害",
    ]
    for name in numeric:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = frame.dropna(subset=numeric).copy()

    # The extractor misclassified Xiahou Yuan as 弓兵 in these rows. The
    # project roster records him as 骑兵; 骑兵克制盾兵, so a 盾兵 attacker
    # receives the disadvantaged 0.87 multiplier.
    frame["兵种乘区_修正"] = frame["兵种乘区"]
    frame.loc[frame["目标"] == "夏侯渊", "兵种乘区_修正"] = 0.87

    general = (
        0.1
        + 0.9
        * (1.0 + (frame["攻击者增伤"] + frame["攻击者兵刃增伤"]) / 100.0)
        * (1.0 - frame["目标净减伤"] / 100.0)
    )
    weapon_taken = 1.0 - frame["目标兵刃净减伤"] / 100.0
    baseline = (
        base_weapon(frame["攻击者武力"].to_numpy(), frame["目标统率"].to_numpy())
        * SKILL_RATE
        * frame["兵力系数_最佳alpha"]
        * frame["兵种乘区_修正"]
        * frame["阵营乘区"]
        * general
        * weapon_taken
    )
    frame["统率差"] = frame["攻击者统率"] - frame["目标统率"]
    frame["无统率差预测"] = baseline
    frame["经验统率差乘区"] = frame["实测伤害"] / baseline

    # All remaining observations have positive command difference.
    x = frame["统率差"].to_numpy(float)
    y = frame["经验统率差乘区"].to_numpy(float)
    target_force = frame["目标武力"].to_numpy(float)
    target_army_ratio = (
        frame["目标受击前兵力"] / frame["目标最大兵力"]
    ).to_numpy(float)

    models = {
        "free_linear": (lambda z, a, b: a + b * z, [1.0, 0.003], (-np.inf, np.inf)),
        "fixed_intercept": (lambda z, b: 1.0 + b * z, [0.003], (-np.inf, np.inf)),
        # Keep the exponent in a plausible range; an unconstrained fit is
        # numerically degenerate on this small sample.
        "power": (
            lambda z, a, b, p: a * (1.0 + b * z) ** p,
            [1.0, 0.003, 1.0],
            ([0.0, 0.0, 0.5], [5.0, 0.02, 2.0]),
        ),
        "one_plus_power": (
            lambda z, a, p: 1.0 + a * (z / 500.0) ** p,
            [0.8, 1.0],
            ([0.0, 0.5], [10.0, 2.0]),
        ),
        # Exploratory wider-exponent version. Keep separate from the bounded
        # candidate above so the result is visible without silently changing
        # the conservative fit used by the simulator.
        "one_plus_power_wide": (
            lambda z, a, p: 1.0 + a * (z / 500.0) ** p,
            [0.8, 1.5],
            ([0.0, 0.5], [10.0, 3.0]),
        ),
        "one_plus_quadratic": (
            lambda z, b, c: 1.0 + b * z + c * z**2,
            [0.002, 0.000001],
            ([-0.02, -0.00001], [0.02, 0.00001]),
        ),
    }
    results = []
    predictions = {}
    for name, (func, p0, bounds) in models.items():
        params, pred, r2, rmse = fit_and_score(func, x, y, p0, bounds)
        predictions[name] = pred
        results.append({
            "model": name,
            "parameters": [float(v) for v in params],
            "r2": float(r2),
            "rmse_multiplier": float(rmse),
        })

    # Diagnostics only: test whether the two low Xiahou Yuan observations are
    # better explained by an omitted target-side variable. These are not
    # promoted to a game formula without new paired samples.
    diagnostics = {
        "delta_plus_target_force": (
            lambda z, a, b, c: a + b * z[0] + c * z[1],
            (x, target_force),
            [1.0, 0.003, 0.0],
        ),
        "delta_plus_target_army_ratio": (
            lambda z, a, b, c: a + b * z[0] + c * z[1],
            (x, target_army_ratio),
            [1.0, 0.003, 0.0],
        ),
    }
    for name, (func, z, p0) in diagnostics.items():
        params, pred, r2, rmse = fit_and_score(func, z, y, p0)
        results.append({
            "model": name,
            "parameters": [float(v) for v in params],
            "r2": float(r2),
            "rmse_multiplier": float(rmse),
        })

    # Keep exploratory target-side regressors out of the candidate formula
    # selection; they are diagnostic evidence, not a proposed mechanic.
    best = min(results[: len(models)], key=lambda row: row["rmse_multiplier"])
    frame["预测乘区_最佳"] = predictions[best["model"]]
    frame["预测伤害_最佳"] = baseline * frame["预测乘区_最佳"]
    frame["误差_最佳"] = frame["实测伤害"] - frame["预测伤害_最佳"]
    frame["相对误差_最佳_%"] = frame["误差_最佳"] / frame["实测伤害"] * 100.0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT_DIR / "兵动若神_清洗后逐条数据.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / "模型对比.json").write_text(
        json.dumps({"excluded_report": EXCLUDED_REPORT, "sample_count": len(frame), "models": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"samples={len(frame)}")
    print(f"excluded_report={EXCLUDED_REPORT}")
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    print(f"best={best['model']}")
    print(frame[["战报", "原文行号", "目标", "统率差", "经验统率差乘区", "实测伤害", "预测伤害_最佳", "误差_最佳"]].to_string(index=False))


if __name__ == "__main__":
    main()
