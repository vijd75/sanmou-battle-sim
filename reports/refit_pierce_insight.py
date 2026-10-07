from pathlib import Path
import json, math
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

CAP = Path(r"D:\battlelog-capture-assistant\csv_output\拟合结果")
OUT = Path(__file__).resolve().parent

def factor(t, m):
    x = 10.0*t/m
    if x >= 9: return 1.0
    if x >= 6: return .063*x+.433
    if x >= 4: return .073*x+.373
    if x >= 1: return .8335922058966468*(1-math.exp(-.20422439236668888*x))+.19638663729131026
    if x >= .1: return .3589214157800344*(1-math.exp(-1.0509781686228445*x))+.11249477230478798
    return .10332192473573393*(1-math.exp(-11.27882258789204*x))+.07203069815884945

def met(y,p):
    e=p-y
    return dict(n=len(y),R2=1-float(e@e)/float(((y-y.mean())**2).sum()),RMSE=float(np.sqrt(np.mean(e*e))),MAE=float(np.mean(np.abs(e))))

def cv(df, ycol, pred, group='战报'):
    rows=[]
    for g in df[group].dropna().unique():
        tr=df[df[group]!=g]; te=df[df[group]==g]
        if len(te)<1: continue
        p=pred(tr,te)
        rows.extend(zip(te[group].astype(str),te[ycol].to_numpy(float),p))
    z=pd.DataFrame(rows,columns=['battle','y','p'])
    return float(np.sqrt(np.mean((z.p-z.y)**2))), float(np.mean(np.abs(z.p-z.y))),len(z)

def weapon_base(force, cmd):
    s=(force-350.0)/42.229892
    sp=np.where(s>40,s,np.log1p(np.exp(np.clip(s,-100,40))))
    return (181.246541*(force+177.097104)+633.945615*42.229892*sp)/(cmd+76.751897)+34.118963

def main():
    # K1 original 161 + unique Dragon Gallop events (exclude its 16 ordinary rows).
    p=CAP/r"破甲验证\全量普通攻击\逐条结果.csv"
    d=pd.read_csv(p,encoding='utf-8-sig')
    d=d[(d['是否普通攻击']==True)&(d['攻击者是否识别']==True)&(~d['是否抵御'].fillna(False))&(~d['是否击杀截断'].fillna(False))].copy()
    # Existing inferred base damage has the prior alpha troop curve embedded. Re-normalize to user-provided relative troop function.
    old=d['兵力系数_最佳alpha'].astype(float).to_numpy()
    new=np.array([factor(a,b) for a,b in zip(d['攻击者当前兵力'],d['攻击者最大兵力'])])
    y=d['观测基础伤害'].astype(float).to_numpy()*old/new
    d['y']=y
    force=d['攻击者武力'].astype(float).to_numpy(); cmd=d['目标统率'].astype(float).to_numpy(); rate=d['攻击者破甲'].astype(float).to_numpy()/100
    def k1pred(k, ix=None): return weapon_base(force if ix is None else force[ix], cmd if ix is None else cmd[ix]*(1-k*rate if ix is None else 1))
    # Recompute effective command per candidate; optimize direct nonlinear error.
    forms=[]
    def optimize(name, fn, bounds):
        f=lambda q: float(np.mean((weapon_base(force,fn(q,cmd,rate))-y)**2))
        res=minimize_scalar(f,bounds=bounds,method='bounded')
        pr=weapon_base(force,fn(res.x,cmd,rate))
        forms.append(dict(dataset='PVP普通攻击161',model=name,param=float(res.x),**met(y,pr)))
        errs=[]
        for battle in d['战报'].dropna().unique():
            tr=np.flatnonzero(d['战报'].to_numpy()!=battle); te=np.flatnonzero(d['战报'].to_numpy()==battle)
            rr=minimize_scalar(lambda v:np.mean((weapon_base(force[tr],fn(v,cmd[tr],rate[tr]))-y[tr])**2),bounds=bounds,method='bounded')
            errs.extend((weapon_base(force[te],fn(rr.x,cmd[te],rate[te]))-y[te]).tolist())
        forms[-1]['LOBO_RMSE']=float(np.sqrt(np.mean(np.square(errs))))
        forms[-1]['LOBO_MAE']=float(np.mean(np.abs(errs)))
        return res.x
    optimize('比例有效统率',lambda k,c,r:c*(1-k*r),(0,1.5))
    optimize('除法有效统率',lambda k,c,r:c/(1+k*r),(0,5))
    optimize('幂函数有效统率',lambda k,c,r:c*np.maximum(1-r,1e-8)**k,(0,3))
    optimize('固定扣统率点数',lambda a,c,r:np.maximum(0,c-a*(r*100)),(0,10))
    # Dragon gallop contributes the same weapon base after removing its known skill coefficient.
    dp=CAP/r"破甲验证\赵云普通攻击与龙胆\逐条结果.csv"
    dragon=pd.read_csv(dp,encoding='utf-8-sig')
    dragon=dragon[(dragon['战法名称']=='七进七出') & (~dragon['是否抵御'].fillna(False)) & (~dragon['是否击杀截断'].fillna(False))].copy()
    dragon['y']=dragon['观测基础伤害'].astype(float)*dragon['兵力系数_最佳alpha'].astype(float)/np.array([factor(a,b) for a,b in zip(dragon['攻击者当前兵力'],dragon['攻击者最大兵力'])])
    zd=dragon['目标统率'].astype(float).to_numpy(); zr=dragon['攻击者破甲'].astype(float).to_numpy()/100; zf=dragon['攻击者武力'].astype(float).to_numpy(); zy=dragon['y'].to_numpy()
    for name,fn,bounds in [('比例有效统率',lambda k,c,r:c*(1-k*r),(0,1.5)),('除法有效统率',lambda k,c,r:c/(1+k*r),(0,5)),('幂函数有效统率',lambda k,c,r:c*np.maximum(1-r,1e-8)**k,(0,3)),('固定扣统率点数',lambda a,c,r:np.maximum(0,c-a*(r*100)),(0,10))]:
        rr=minimize_scalar(lambda v:np.mean((weapon_base(zf,fn(v,zd,zr))-zy)**2),bounds=bounds,method='bounded')
        forms.append(dict(dataset='七进七出80',model=name,param=float(rr.x),**met(zy,weapon_base(zf,fn(rr.x,zd,zr)))))
    # Pooled fit, with each battle held out in turn. Source and ordinary attack are normalized to base damage first.
    pool_force=np.r_[force,zf]; pool_cmd=np.r_[cmd,zd]; pool_rate=np.r_[rate,zr]; pool_y=np.r_[y,zy]
    pool_battle=np.r_[d['战报'].astype(str).to_numpy(),dragon['战报'].astype(str).to_numpy()]
    for name,fn,bounds in [('比例有效统率',lambda k,c,r:c*(1-k*r),(0,1.5)),('除法有效统率',lambda k,c,r:c/(1+k*r),(0,5)),('幂函数有效统率',lambda k,c,r:c*np.maximum(1-r,1e-8)**k,(0,3)),('固定扣统率点数',lambda a,c,r:np.maximum(0,c-a*(r*100)),(0,10))]:
        rr=minimize_scalar(lambda v:np.mean((weapon_base(pool_force,fn(v,pool_cmd,pool_rate))-pool_y)**2),bounds=bounds,method='bounded')
        row=dict(dataset='普攻+七进七出241',model=name,param=float(rr.x),**met(pool_y,weapon_base(pool_force,fn(rr.x,pool_cmd,pool_rate))))
        err=[]
        for battle in np.unique(pool_battle):
            tr=pool_battle!=battle; te=~tr
            if tr.sum()==0 or te.sum()==0: continue
            rcv=minimize_scalar(lambda v:np.mean((weapon_base(pool_force[tr],fn(v,pool_cmd[tr],pool_rate[tr]))-pool_y[tr])**2),bounds=bounds,method='bounded')
            err.extend((weapon_base(pool_force[te],fn(rcv.x,pool_cmd[te],pool_rate[te]))-pool_y[te]).tolist())
        row['LOBO_RMSE']=float(np.sqrt(np.mean(np.square(err))))
        row['LOBO_MAE']=float(np.mean(np.abs(err)))
        forms.append(row)
    # K2: re-use raw normalized base damage, correct for troop-factor only, then compare transformations.
    kp=CAP/r"谋略伤害\草船借箭\看破拟合\全部样本_看破直接拟合逐条.csv"
    q=pd.read_csv(kp,encoding='utf-8-sig')
    q=q[(~q['是否抵御'].fillna(False))&(~q['是否击杀截断'].fillna(False))].copy()
    # D_obs currently normalized using factor=1 in most original fit; reconstruct exact multiplier from source's observed D and old troop field.
    # raw multiplier column '兵力系数' is the prior soldier factor; replace it with current/max factor.
    oldq=pd.to_numeric(q['兵力系数'],errors='coerce').fillna(1).to_numpy()
    maxq=q['攻击者状态JSON'].map(lambda s: json.loads(s).get('最大兵力') if isinstance(s,str) else np.nan).astype(float).to_numpy()
    troops=pd.to_numeric(q['攻击者当前兵力'],errors='coerce').to_numpy()
    newq=np.array([factor(a,b) if np.isfinite(b) and b>0 else np.nan for a,b in zip(troops,maxq)])
    yq=pd.to_numeric(q['D_obs'],errors='coerce').to_numpy()*oldq/newq
    q['y']=yq
    ai=q['攻击者智力'].astype(float).to_numpy(); ti=q['目标智力'].astype(float).to_numpy(); tc=q['目标统率'].astype(float).to_numpy(); look=q['攻击者看破'].astype(float).to_numpy()/100
    def sb(a,t,c):
        z=422.88527020+.62709505*a-.30029221*t-.54813767*c
        for b,x,y,z0 in ((120,1.46788045,-.00266870,-.00173418),(200,-1.20322956,.00197171,.00256683),(500,.60127771,.00643166,-.00430132),(540,1.53798160,-.00248899,-.00014062),(620,9.20652279,-.02263491,-.00314806)):
            h=np.maximum(a-b,0); z+=h*(x+y*t+z0*c)
        return z
    # y is zero-look base damage; infer equivalent target intellect under each transformation and compare the game base formula.
    # Candidate score uses direct strategy-base predictions with known attacker and target command.
    for name,fn,bounds in [('百分比',lambda k:ti*(1-k*look),(0,2)),('固定扣智力',lambda a:np.maximum(0,ti-a*look*100),(0,5)),('除法',lambda k:ti/(1+k*look),(0,5)),('幂函数',lambda k:ti*np.maximum(1-look,1e-8)**k,(0,5))]:
        r=minimize_scalar(lambda v:np.mean((sb(ai,fn(v),tc)-yq)**2),bounds=bounds,method='bounded')
        pred=sb(ai,fn(r.x),tc)
        row=dict(dataset='草船借箭379',model=name,param=float(r.x),**met(yq,pred))
        errs=[]
        for battle in q['战报'].dropna().unique():
            tr=np.flatnonzero(q['战报'].to_numpy()!=battle); te=np.flatnonzero(q['战报'].to_numpy()==battle)
            if not len(tr) or not len(te): continue
            rr=minimize_scalar(lambda v:np.mean((sb(ai[tr],fn(v)[tr],tc[tr])-yq[tr])**2),bounds=bounds,method='bounded')
            errs.extend((sb(ai[te],fn(rr.x)[te],tc[te])-yq[te]).tolist())
        row['LOBO_RMSE']=float(np.sqrt(np.mean(np.square(errs)))) if errs else np.nan
        row['LOBO_MAE']=float(np.mean(np.abs(errs))) if errs else np.nan
        forms.append(row)
    # The full set is strongly confounded by battle: most insight rates occur in only one battle.
    # Retain only attacker-target pairs in the one battle that contains both 0% and 43% insight.
    match=q[q['战报'].astype(str).eq('20260918_214615_44a38bc5')].copy()
    match=match.groupby(['攻击者','目标'],group_keys=False).filter(lambda x:x['攻击者看破'].nunique()>1)
    mi=match['攻击者智力'].astype(float).to_numpy(); mt=match['目标智力'].astype(float).to_numpy(); mc=match['目标统率'].astype(float).to_numpy(); mr=match['攻击者看破'].astype(float).to_numpy()/100; my=match['y'].astype(float).to_numpy()
    for name,fn,bounds in [('百分比',lambda k:mt*(1-k*mr),(0,2)),('固定扣智力',lambda a:np.maximum(0,mt-a*mr*100),(0,5)),('除法',lambda k:mt/(1+k*mr),(0,5)),('幂函数',lambda k:mt*np.maximum(1-mr,1e-8)**k,(0,5))]:
        r=minimize_scalar(lambda v:np.mean((sb(mi,fn(v),mc)-my)**2),bounds=bounds,method='bounded')
        row=dict(dataset='同战报同攻防双方91',model=name,param=float(r.x),**met(my,sb(mi,fn(r.x),mc)))
        forms.append(row)
    match.to_csv(OUT/'2026-09-25-草船看破同战报对照91条.csv',index=False,encoding='utf-8-sig')
    # Save compact fit summary and clean row sources for reproducibility.
    pd.DataFrame(forms).to_csv(OUT/'2026-09-25-破甲看破重拟合_模型对比.csv',index=False,encoding='utf-8-sig')
    q.to_csv(OUT/'2026-09-25-草船看破重拟合_逐条.csv',index=False,encoding='utf-8-sig')
    d.to_csv(OUT/'2026-09-25-普攻破甲重拟合_逐条.csv',index=False,encoding='utf-8-sig')
    print(pd.DataFrame(forms).to_string(index=False))
    print('Dragon rows',len(dragon),'reports',dragon['战报'].nunique(),'sources',dragon['战法名称'].value_counts().to_dict())

if __name__=='__main__': main()
