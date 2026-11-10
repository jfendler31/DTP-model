import pandas as pd, numpy as np, json
g=pd.read_csv('data/games_2026-27.csv')
XB={k:v.strip() for k,v in json.load(open('data/xwalk_cbbd_kp.json')).items()}; XB.update({'Miami':'Miami FL','New Orleans':'LSU New Orleans'})
g['kp']=g.team.map(lambda s:XB.get(s,s)); g['kpo']=g.opp.map(lambda s:XB.get(s,s))
LG=g.p3m.sum()/g.p3a.sum()
# 3PT points above a league-average shooter on the same attempts
g['x3']=3*(g.p3m-LG*g.p3a)
key=g.set_index(['date','kp','kpo'])
def side_luck(date,team,opp):
    try: a=key.loc[(date,team,opp)]; b=key.loc[(date,opp,team)]
    except KeyError: return np.nan,np.nan,np.nan
    if isinstance(a,pd.DataFrame): a=a.iloc[0]; b=b.iloc[0]
    return a.x3-b.x3, a.p3a, b.p3a
print(f'league 3P% {LG:.3f}')
# 1) Jon's bets
B=pd.read_csv('data/bets/jon_bets_2026-27.csv',encoding='utf-8-sig')
r=[side_luck(x.date,x.team,x.opp) for x in B.itertuples()]
B['luck3']=[v[0] for v in r]; B['my3pa']=[v[1] for v in r]; B['opp3pa']=[v[2] for v in r]
print('\nJon bets (n=%d, matched %d)'%(len(B),B.luck3.notna().sum()))
print(B.groupby('res').luck3.agg(['count','mean']).round(2).to_string())
print('all bets mean 3PT luck', round(B.luck3.mean(),2), '| share of bets with negative 3PT luck', round((B.luck3<0).mean(),2))
print('3PA: mine', round(B.my3pa.mean(),1), 'opp', round(B.opp3pa.mean(),1))
# 2) all graded card games, model side
L=pd.read_csv('data/grades/grade_log.csv'); L=L[(L.date>='2026-11-02')&L.res_ref.isin(['W','L'])]
out=[]
for x in L.itertuples():
    opp=x.away if x.side==x.home else x.home
    v=side_luck(x.date,x.side,opp); out.append(v[0])
L['luck3']=out; L=L[L.luck3.notna()]
print('\nCard model side, all graded games (n=%d)'%len(L))
print(L.groupby('res_ref').luck3.agg(['count','mean']).round(2).to_string())
print('overall mean', round(L.luck3.mean(),2), '| SD per game', round(L.luck3.std(),2))
L['dog']=np.where(L.side==L.home, L.ref>0, L.ref<0)
print(L.groupby('dog').luck3.agg(['count','mean']).round(2).to_string())
# 3) is it structural? opponents of model side vs their prior-season 3P% (KenPom 2025-26)
m=pd.read_csv('data/kenpom/history/misc-stats_2026.csv'); m=m[m.ConfOnly.astype(str).str.lower()!='true'].set_index('TeamName')
L['opp']=np.where(L.side==L.home,L.away,L.home)
L['opp_prev3']=L.opp.map(m.FG3Pct); L['side_prev3']=L.side.map(m.FG3Pct)
print('\nprior-season 3P%: model-side teams', round(L.side_prev3.mean(),2), '| their opponents', round(L.opp_prev3.mean(),2))

# 4) dog/fav split with team-specific baselines (prior-season 3P% offense and 3P% defense, KenPom 2025-26)
f3=m.FG3Pct/100; o3=m.OppFG3Pct/100; lg_prev=(m.FG3Pct.mean())/100
def xexp(date,team,opp):
    try: a=key.loc[(date,team,opp)]; b=key.loc[(date,opp,team)]
    except KeyError: return np.nan
    if isinstance(a,pd.DataFrame): a=a.iloc[0]; b=b.iloc[0]
    if team not in f3 or opp not in f3: return np.nan
    ea=f3[team]+o3[opp]-lg_prev; eb=f3[opp]+o3[team]-lg_prev
    return 3*(a.p3m-ea*a.p3a) - 3*(b.p3m-eb*b.p3a)
L['luck3_adj']=[xexp(x.date,x.side,x.opp) for x in L.itertuples()]
print('\nteam-adjusted 3PT luck (prior-season offense/defense 3P%):')
print(L.groupby('dog').luck3_adj.agg(['count','mean']).round(2).to_string())
print(L.groupby('res_ref').luck3_adj.agg(['count','mean']).round(2).to_string())
# 5) persistence: does a team's 3P% in earlier games this season predict its 3P% in the next game?
g=g.sort_values('date'); g['cum3m']=g.groupby('team').p3m.cumsum()-g.p3m; g['cum3a']=g.groupby('team').p3a.cumsum()-g.p3a
h=g[g.cum3a>=15].copy(); h['prev']=h.cum3m/h.cum3a; h['now']=h.p3m/h.p3a
w=h.p3a; b=np.polyfit(h.prev-LG,h.now-LG,1,w=np.sqrt(w))[0]
print(f'\npersistence: next-game 3P% vs earlier-games 3P% this season, slope {b:.2f} (n={len(h)} team-games)')
# 6) Jon's bets: dog share and dog luck
B['dog']=B.line>0
print('\nJon bets dog share', round(B.dog.mean(),2)); print(B.groupby('dog').luck3.agg(['count','mean']).round(2).to_string())
