import os
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

ROOT = Path(r"D:\battlelog-capture-assistant\csv_output")
candidates = [p for p in ROOT.rglob("*.csv") if p.name == "\u9010\u6761\u8bef\u5dee.csv" and "_v10" in str(p) and "\u8349\u8239\u501f\u7bad" in str(p)]
if len(candidates) != 1:
    raise RuntimeError(f"expected one v10 input, found {len(candidates)}")
CSV = candidates[0]
OUT = CSV.parent.parent / "\u8c0b\u7565\u57fa\u7840\u4f24\u5bb3_v11_\u6307\u6570\u6a21\u578b"
OUT.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(CSV, encoding="utf-8-sig")
df = df[df["攻击者看破"] == 0].copy()
I = df["攻击者智力"].to_numpy(dtype=float)
Ti = df["目标智力"].to_numpy(dtype=float)
Tc = df["目标统率"].to_numpy(dtype=float)
D = df["D"].to_numpy(dtype=float)
X = (I, Ti, Tc)

def model_dual(X, K, a, p, b, q, C):
    I, Ti, Tc = X
    E = Ti + Tc
    return K * (I + a) ** p / (E + b) ** q + C

def model_power_diff(X, K, p, C):
    I, Ti, Tc = X
    return K * (I - (Ti + Tc) / 2) ** p + C

def model_ratio_pow(X, K, p, C):
    I, Ti, Tc = X
    return K * (I / (Ti + Tc + 1)) ** p + C

def model_I_pow_lin_def(X, K, a, p, b, C):
    I, Ti, Tc = X
    E = Ti + Tc
    return K * (I + a) ** p / (E + b) + C

def model_lin_I_pow_def(X, K, a, b, q, C):
    I, Ti, Tc = X
    E = Ti + Tc
    return K * (I + a) / (E + b) ** q + C

models = {
    "D=K(I+a)^p/(def+b)^q+C": (model_dual, [1000, -200, 1.0, 100, 1.0, -50], ([0, -1000, 0.5, -500, 0.5, -500], [5000, 1000, 2.0, 2000, 2.0, 500])),
    "D=K(I-def/2)^p+C": (model_power_diff, [100, 1.0, 0], ([0, 0.5, -500], [5000, 2.0, 500])),
    "D=K(I/(Ti+Tc))^p+C": (model_ratio_pow, [1000, 1.0, 0], ([0, 0.5, -500], [50000, 2.0, 500])),
    "D=K(I+a)^p/(def+b)+C": (model_I_pow_lin_def, [1000, -200, 1.0, 100, -50], ([0, -1000, 0.5, -500, -500], [5000, 1000, 2.0, 2000, 500])),
    "D=K(I+a)/(def+b)^q+C": (model_lin_I_pow_def, [1000, -200, 100, 1.0, -50], ([0, -1000, -500, 0.5, -500], [5000, 1000, 2000, 2.0, 500])),
}

results = []
best = None
best_rmse = np.inf
for name, (func, p0, bounds) in models.items():
    try:
        popt, _ = curve_fit(func, X, D, p0=p0, bounds=bounds, maxfev=200000)
        pred = func(X, *popt)
        if not np.all(np.isfinite(pred)):
            raise ValueError("预测值包含非有限数")
        ss_res = np.sum((D - pred) ** 2)
        ss_tot = np.sum((D - D.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot
        rmse = np.sqrt(np.mean((D - pred) ** 2))
        mape = np.mean(np.abs((D - pred) / np.maximum(D, 1))) * 100
        results.append({"模型": name, "参数": str([round(float(p), 6) for p in popt]), "R2": r2, "RMSE": rmse, "MAPE_%": mape})
        if rmse < best_rmse:
            best_rmse = rmse
            best = (name, func, popt, pred)
    except Exception as exc:
        results.append({"模型": name, "参数": "失败: " + str(exc), "R2": np.nan, "RMSE": np.nan, "MAPE_%": np.nan})

def model_v10(X, K, a, b, C):
    I, Ti, Tc = X
    return K * (I + a) / (Ti + Tc + b) + C

popt_v10, _ = curve_fit(model_v10, X, D, p0=[2226.52, -292.31, 125.10, -36.37], maxfev=200000)
pred_v10 = model_v10(X, *popt_v10)
r2_v10 = 1 - np.sum((D - pred_v10) ** 2) / np.sum((D - D.mean()) ** 2)
rmse_v10 = np.sqrt(np.mean((D - pred_v10) ** 2))
mape_v10 = np.mean(np.abs((D - pred_v10) / np.maximum(D, 1))) * 100

res_df = pd.DataFrame(results).sort_values("RMSE", na_position="last").reset_index(drop=True)
res_df.to_csv(os.path.join(OUT, "模型对比.csv"), index=False, encoding="utf-8-sig")
print("=== 指数模型对比 ===")
print(res_df.to_string(index=False))
print(f"\n=== v10 除法模型对照 ===\nR2={r2_v10:.6f}, RMSE={rmse_v10:.4f}, MAPE={mape_v10:.2f}%")
if best:
    best_name, best_func, best_popt, best_pred = best
    df["预测_D"] = best_pred
    df["残差"] = D - best_pred
    df.to_csv(os.path.join(OUT, "逐条误差_最优.csv"), index=False, encoding="utf-8-sig")
    print("最优模型:", best_name)
    print("最优参数:", [float(x) for x in best_popt])
print("输出目录:", OUT)
