import pandas as pd, numpy as np, sys
g=pd.read_csv('data/grades/grade_log.csv'); g=g[g.date>='2026-11-03'].copy()
h=pd.read_csv('data/kenpom/height_2026-11-07.csv').set_index('TeamName').Continuity
R={d:pd.read_csv(f'data/ratings/ratings_{d}.csv').set_index('team') for d in g.date.unique()}
def dz(d,t,f,thr):
    r=R[d]
    if t not in r.index or r.loc[t,'n_games']==0: return 0.0, None
    c=h.get(t,np.nan)
    if not (c<=thr): return 0.0, c
    x=r.loc[t]; N,K=x.n_games,x.K; l0=N/(N+K); l1=N/(N+K*f)
    if x.method=='early': d_=(l1-l0)*(x.surprise if pd.notna(x.surprise) else 0)
    else: d_=(l1-l0)*(x.z_inseason-x.z_prior)
    return d_, c
def res(m,ref,side_home):
    v=m+ref
    if abs(v)<1e-9: return 'P'
    return 'W' if (v>0)==side_home else 'L'
def run(f,thr,show=False):
    rows=[]
    for x in g.itertuples():
        dh,ch=dz(x.date,x.home,f,thr); da,ca=dz(x.date,x.away,f,thr)
        draw=-9.5*(dh-da)
        if abs(draw)<0.05: continue
        slope=1.2 if abs(x.model_adj-x.model_raw)>0.05 else 1.0
        adj1=x.model_adj+draw*slope
        e0=x.ref-x.model_adj; e1=x.ref-adj1
        h0,h1=e0>0,e1>0
        r1=res(x.home_margin,x.ref,h1); rc1=res(x.home_margin,x.close,h1) if pd.notna(x.close) else ''
        clv1=(x.ref-x.close if h1 else x.close-x.ref) if pd.notna(x.close) else np.nan
        cover=x.home_margin+x.ref   # + = home covered the reference
        rows.append(dict(date=x.date,away=x.away,home=x.home,cont_a=ca,cont_h=ch,ref=x.ref,close=x.close,adj0=x.model_adj,adj1=round(adj1,1),shift=round(draw*slope,2),
                         edge0=round(abs(e0),1),side0=x.side,edge1=round(abs(e1),1),side1=(x.home if h1 else x.away),flip=h0!=h1,res0=x.res_ref,res1=r1,clv0=x.clv,clv1=clv1,
                         dir_ok=np.sign(-draw)==np.sign(cover) if cover!=0 else np.nan, cover=cover))
    return pd.DataFrame(rows)
pd.set_option('display.width',250,'display.max_rows',200)
for f,thr,lab in [(0.5,0.0,'K x0.5, continuity 0%'),(0.5,0.05,'K x0.5, continuity <5%'),(0.5,0.10,'K x0.5, continuity <10%'),(0.25,0.0,'K x0.25, continuity 0%')]:
    d=run(f,thr)
    a=d[d['shift'].abs()>=0.5]; fl=d[d.flip]
    wr=lambda s:f"{(s=='W').sum()}-{(s=='L').sum()}-{(s=='P').sum()}"
    print(f"\n{lab}: games touched {len(d)}, shift>=0.5 {len(a)}, mean |shift| {d['shift'].abs().mean():.2f}, max {d['shift'].abs().max():.2f}; side flips {len(fl)}: old {wr(fl.res0)} -> new {wr(fl.res1)}; flip CLV old {fl.clv0.mean():+.2f} new {fl.clv1.mean():+.2f}")
    print(f"   direction of the extra move vs result (all touched, non-push): right {int(d.dir_ok.sum())} / {int(d.dir_ok.notna().sum())}; shift>=0.5: right {int(a['dir_ok'].sum())} / {int(a['dir_ok'].notna().sum())}")
    # correlation: does shift predict cover beyond the reference? and close CLV
    dd=d.dropna(subset=['close'])
    print(f"   corr(-shift, cover vs ref) {np.corrcoef(-d['shift'],d.cover)[0,1]:+.2f} (n={len(d)}); corr(-shift, close move toward home: ref-close) {np.corrcoef(-dd['shift'], dd.ref-dd.close)[0,1]:+.2f}")
    if lab.startswith('K x0.5, continuity 0%'):
        d.to_csv(sys.argv[1],index=False)
        print(d.sort_values('shift',key=abs,ascending=False)[['date','away','home','cont_a','cont_h','ref','close','adj0','adj1','shift','side0','edge0','side1','edge1','flip','res0','res1','clv0','clv1','cover']].head(40).to_string(index=False))
